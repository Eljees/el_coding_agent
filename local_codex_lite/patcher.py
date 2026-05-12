from __future__ import annotations

import shutil
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path

from .safety import is_inside_workspace, is_sensitive_path


# ---------------------------------------------------------------------------
# Runtime-fix context (formerly runtime_fix.py)
# ---------------------------------------------------------------------------

TRACEBACK_PATH_RE = re.compile(r'File "([^"]+)"(?:, line \d+)?')


@dataclass(frozen=True)
class RuntimeFixContext:
    target_path: Path
    traceback_text: str
    current_text: str


def detect_runtime_fix_context(task: str, evidence_text: str, workspace_root: Path) -> RuntimeFixContext | None:
    if not evidence_text.strip():
        return None
    if "traceback" not in evidence_text.lower():
        return None

    candidates: list[Path] = []
    seen: set[Path] = set()
    for raw_path in TRACEBACK_PATH_RE.findall(evidence_text):
        path = Path(raw_path)
        if path.suffix.lower() != ".py":
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(workspace_root)
        except ValueError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        candidates.append(resolved)

    if len(candidates) != 1:
        return None

    target_path = candidates[0]
    current_text = target_path.read_text(encoding="utf-8", errors="replace")
    return RuntimeFixContext(
        target_path=target_path,
        traceback_text=evidence_text.strip(),
        current_text=current_text,
    )


# ---------------------------------------------------------------------------
# Patch validation and application
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PatchValidationResult:
    ok: bool
    errors: list[str]


def validate_diff(diff_text: str, workspace_root: Path, allow_sensitive_read: bool = False) -> PatchValidationResult:
    errors: list[str] = []
    if not diff_text.strip():
        return PatchValidationResult(ok=False, errors=["empty diff"])
    if not _has_substantive_changes(diff_text):
        return PatchValidationResult(ok=False, errors=["no-op diff"])
    current: Path | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            raw = line[6:].strip()
            if raw == "/dev/null":
                continue
            candidate = (workspace_root / raw).resolve()
            if not is_inside_workspace(candidate, workspace_root):
                errors.append(f"outside workspace: {raw}")
            if not allow_sensitive_read and is_sensitive_path(candidate):
                errors.append(f"sensitive path blocked: {raw}")
            current = candidate
    if current is None:
        errors.append("no file paths found")
    return PatchValidationResult(ok=not errors, errors=errors)


def _has_substantive_changes(diff_text: str) -> bool:
    removed: list[str] = []
    added: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith(("diff --git", "--- ", "+++ ", "@@")):
            continue
        if line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    if not removed and not added:
        return False
    if removed == added:
        return False
    return [_semantic_line(line) for line in removed] != [_semantic_line(line) for line in added]


def _semantic_line(line: str) -> str:
    line = line.strip()
    if "#" in line:
        line = line.split("#", 1)[0].rstrip()
    return "".join(line.split())


def backup_paths(paths: list[Path], workspace_root: Path) -> Path:
    backup_root = workspace_root / ".local-codex-lite" / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = backup_root / "current"
    stamp.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.exists() and path.is_file():
            rel = path.relative_to(workspace_root)
            target = stamp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return stamp


def apply_patch(diff_text: str, workspace_root: Path) -> subprocess.CompletedProcess[str]:
    patch_file = workspace_root / ".local-codex-lite" / "patch.diff"
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_file.write_text(diff_text, encoding="utf-8")
    git_root = _discover_git_root(workspace_root)
    if git_root is not None:
        directory_arg: list[str] = []
        strategy = "git_root_relative"
        if git_root != workspace_root:
            try:
                rel_dir = workspace_root.relative_to(git_root).as_posix()
            except ValueError:
                rel_dir = ""
            if rel_dir:
                # The model is asked (see prompts.py) to include the workspace
                # prefix in diff paths when nested under a larger repo. If it
                # honored that instruction we MUST NOT also pass --directory or
                # the prefix gets applied twice and git apply fails with
                # "no such file in working directory".
                if _diff_paths_already_prefixed(diff_text, rel_dir):
                    strategy = "in_diff_prefix"
                else:
                    directory_arg = ["--directory", rel_dir]
                    strategy = "directory_prefix"
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", *directory_arg, str(patch_file)],
            cwd=git_root,
            capture_output=True,
            text=True,
            check=False,
        )
        # Surface the chosen strategy on the returned object so callers (cli.py)
        # can persist it into events.jsonl without changing the public signature.
        try:
            setattr(result, "git_apply_strategy", strategy)
        except (AttributeError, TypeError):
            pass
        return result
    raise RuntimeError("git repo required for patch apply in MVP")


_DIFF_PATH_RE = re.compile(r"^(?:---|\+\+\+) [ab]/(?P<path>.+?)\s*$", re.MULTILINE)


def _diff_paths_already_prefixed(diff_text: str, rel_dir: str) -> bool:
    """Return True when at least one --- a/<path> or +++ b/<path> in the diff
    already starts with ``rel_dir`` (followed by a path separator).

    We deliberately accept "at least one" rather than requiring all paths to be
    prefixed: mixed diffs are rare in practice, and if even a single path is
    pre-prefixed then passing --directory will mangle that path. The validator
    in ``validate_diff`` is the authoritative check for path consistency; this
    helper only decides which apply strategy to use.
    """
    if not rel_dir:
        return False
    needle = rel_dir.rstrip("/") + "/"
    for match in _DIFF_PATH_RE.finditer(diff_text):
        candidate = match.group("path").strip()
        if candidate == "/dev/null":
            continue
        if candidate.startswith(needle):
            return True
    return False


def _discover_git_root(workspace_root: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(workspace_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import WorkspaceConfig
from .path_filters import path_has_blocked_dir
from .safety import can_read_path, is_inside_workspace
from .targeting import detect_task_target


@dataclass(frozen=True)
class FileChunk:
    path: Path
    content: str


@dataclass(frozen=True)
class RankedWorkspaceFile:
    path: Path
    score: int
    reasons: tuple[str, ...]


# --- ranking score weights -------------------------------------------------
# These weights tune how aggressively rank_workspace_files prefers files that
# match the task.  The exact numbers were tuned by hand; the names exist so
# changes have to be justified instead of dropped into a magic-number jungle.
SCORE_TARGET_PATH_EXACT       = 260   # exact match of the resolved task target
SCORE_TARGET_BASENAME         = 220   # basename matches the task target
SCORE_TASK_MENTIONS_PATH      = 140   # full rel-path appears verbatim in the task
SCORE_TASK_MENTIONS_TESTS     = 140   # task talks about tests + file is a test
SCORE_TASK_MENTIONS_BASENAME  = 110   # basename appears in the task text
SCORE_TASK_MENTIONS_STEM      = 90    # stem (basename minus extension) appears
SCORE_IMPORTANT_BASENAME      = 28    # well-known project file (pyproject.toml, ...)
SCORE_CONFIG_FILE             = 18    # .toml/.yaml/.json/.ini config flavor
SCORE_PY_SOURCE               = 14    # generic python source bonus
SCORE_DOC_FILE                = 8     # .md/.rst documentation
SCORE_TESTS_DIR               = 16    # lives under tests/
SCORE_TOKEN_EXACT             = 35    # task token equals basename or stem
SCORE_TOKEN_PARTIAL           = 10    # task token is a substring of the path
SCORE_SAME_DIR_BOOST          = 8     # neighbour of a high-scoring file
SCORE_STRONG_DIR_THRESHOLD    = 70    # min score for a directory to "pull in" peers


_IMPORTANT_BASENAMES = {
    "pyproject.toml",
    "readme.md",
    "readme.rst",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "noxfile.py",
    "conftest.py",
    "__init__.py",
    "__main__.py",
    "main.py",
    "app.py",
    "cli.py",
    "doctor.py",
    "workspace.py",
    "planner.py",
    "patcher.py",
    "llm_client.py",
    "safety.py",
    "config.py",
}

_TEST_HINTS = {"test", "tests", "pytest", "validation", "doctor", "preview", "cli", "patch", "safety"}


def build_tree(root: Path, config: WorkspaceConfig) -> list[str]:
    root = root.resolve()
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        rel_path = Path(rel)
        if path_has_blocked_dir(rel_path.parts[:-1]):
            continue
        if any(_path_matches(rel_path, pattern) for pattern in config.exclude_globs):
            continue
        if config.include_globs and not any(_path_matches(rel_path, pattern) for pattern in config.include_globs):
            continue
        lines.append(rel)
    return lines


def rank_workspace_files(root: Path, task: str, config: WorkspaceConfig) -> list[RankedWorkspaceFile]:
    root = root.resolve()
    task_lower = task.lower()
    task_target = detect_task_target(task, root)
    ranked: list[RankedWorkspaceFile] = []
    for rel in build_tree(root, config):
        path = root / rel
        score, reasons = _score_workspace_file(rel, task_lower, task_target.path if task_target else None)
        ranked.append(RankedWorkspaceFile(path=path, score=score, reasons=tuple(reasons)))

    if not ranked:
        return []

    strong_dirs = _find_strong_dirs(ranked)
    if strong_dirs:
        boosted: list[RankedWorkspaceFile] = []
        for item in ranked:
            score = item.score
            reasons = list(item.reasons)
            if item.path.parent in strong_dirs:
                score += SCORE_SAME_DIR_BOOST
                reasons.append("same directory as strong match")
            boosted.append(RankedWorkspaceFile(path=item.path, score=score, reasons=tuple(reasons)))
        ranked = boosted

    ranked.sort(key=lambda item: (-item.score, item.path.as_posix().lower()))
    return ranked


def select_relevant_files(root: Path, task: str, config: WorkspaceConfig) -> list[Path]:
    return [item.path for item in rank_workspace_files(root, task, config)[:6]]


def summarize_ranked_files(
    root: Path,
    task: str,
    config: WorkspaceConfig,
    allow_sensitive_read: bool,
    limit: int = 5,
) -> list[RankedWorkspaceFile]:
    ranked = rank_workspace_files(root, task, config)
    visible: list[RankedWorkspaceFile] = []
    for item in ranked:
        if not can_read_path(item.path, root, allow_sensitive_read=allow_sensitive_read):
            continue
        visible.append(item)
        if len(visible) >= limit:
            break
    return visible


def read_file_chunks(root: Path, paths: list[Path], max_bytes: int, allow_sensitive_read: bool) -> list[FileChunk]:
    chunks: list[FileChunk] = []
    for path in paths:
        if not is_inside_workspace(path, root):
            continue
        if not can_read_path(path, root, allow_sensitive_read=allow_sensitive_read):
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > max_bytes:
            continue
        chunks.append(FileChunk(path=path, content=path.read_text(encoding="utf-8", errors="replace")))
    return chunks


def compact_context(
    root: Path,
    task: str,
    config: WorkspaceConfig,
    allow_sensitive_read: bool,
    *,
    max_tree_entries: int = 80,
    max_excerpt_chars: int = 6000,
) -> str:
    tree = build_tree(root, config)[:max_tree_entries]
    relevant = select_relevant_files(root, task, config)
    chunks = read_file_chunks(root, relevant, config.max_file_bytes, allow_sensitive_read)
    parts = ["# Tree", *tree, "", "# Relevant files"]
    for chunk in chunks:
        parts.append(f"## {chunk.path.relative_to(root).as_posix()}")
        parts.append(chunk.content[: min(config.max_file_bytes, max_excerpt_chars)])
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def _score_workspace_file(rel: str, task_lower: str, intended_target: str | None = None) -> tuple[int, list[str]]:
    rel_lower = rel.lower()
    basename = Path(rel).name.lower()
    stem = Path(rel).stem.lower()
    parts = Path(rel).parts
    score = 0
    reasons: list[str] = []

    if intended_target:
        target_lower = intended_target.lower()
        target_basename = Path(target_lower).name
        if rel_lower == target_lower:
            score += SCORE_TARGET_PATH_EXACT
            reasons.append("task target path")
        elif basename == target_basename:
            score += SCORE_TARGET_BASENAME
            reasons.append("task target filename")

    if rel_lower in task_lower:
        score += SCORE_TASK_MENTIONS_PATH
        reasons.append("task mentions path")
    elif basename in task_lower:
        score += SCORE_TASK_MENTIONS_BASENAME
        reasons.append("task mentions filename")
    elif stem and stem in task_lower:
        score += SCORE_TASK_MENTIONS_STEM
        reasons.append("task mentions stem")

    if _task_mentions_tests(task_lower):
        if "tests" in rel_lower or basename.startswith("test_") or basename.endswith("_test.py"):
            score += SCORE_TASK_MENTIONS_TESTS
            reasons.append("task mentions tests")

    if basename in _IMPORTANT_BASENAMES:
        score += SCORE_IMPORTANT_BASENAME
        reasons.append("important project file")

    if basename.startswith("config.") or basename.startswith("settings.") or basename.endswith((".toml", ".yaml", ".yml", ".json", ".ini")):
        score += SCORE_CONFIG_FILE
        reasons.append("config file")

    if basename.endswith(".py"):
        score += SCORE_PY_SOURCE
        reasons.append("python source")
    elif basename.endswith((".md", ".rst")):
        score += SCORE_DOC_FILE
        reasons.append("documentation file")

    if parts and parts[0] == "tests":
        score += SCORE_TESTS_DIR
        reasons.append("tests directory")

    for token in _task_tokens(task_lower):
        if len(token) < 3:
            continue
        if token == basename or token == stem:
            score += SCORE_TOKEN_EXACT
            reasons.append(f"matched token {token}")
            break
        if token in rel_lower:
            score += SCORE_TOKEN_PARTIAL
            reasons.append(f"matched token {token}")
            break

    if not reasons:
        reasons.append("baseline ranking")

    return score, reasons


def _task_tokens(task_lower: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9_]+", task_lower) if token]


def _task_mentions_tests(task_lower: str) -> bool:
    tokens = set(_task_tokens(task_lower))
    return any(token in tokens for token in _TEST_HINTS)


def _find_strong_dirs(ranked: list[RankedWorkspaceFile]) -> set[Path]:
    by_dir: dict[Path, int] = {}
    for item in ranked:
        current = by_dir.get(item.path.parent, -1)
        if item.score > current:
            by_dir[item.path.parent] = item.score
    return {directory for directory, score in by_dir.items() if score >= SCORE_STRONG_DIR_THRESHOLD}


def _path_matches(rel_path: Path, pattern: str) -> bool:
    if rel_path.match(pattern):
        return True
    if pattern.startswith("**/") and rel_path.match(pattern[3:]):
        return True
    return False

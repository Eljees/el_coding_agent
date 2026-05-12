from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import WorkspaceConfig
from .safety import can_read_path, is_inside_workspace


@dataclass(frozen=True)
class FileChunk:
    path: Path
    content: str


@dataclass(frozen=True)
class RankedWorkspaceFile:
    path: Path
    score: int
    reasons: tuple[str, ...]


_BLOCKED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".local-codex-lite",
}

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
        if any(part in _BLOCKED_DIRS for part in rel_path.parts[:-1]):
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
    ranked: list[RankedWorkspaceFile] = []
    for rel in build_tree(root, config):
        path = root / rel
        score, reasons = _score_workspace_file(rel, task_lower)
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
                score += 8
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


def _score_workspace_file(rel: str, task_lower: str) -> tuple[int, list[str]]:
    rel_lower = rel.lower()
    basename = Path(rel).name.lower()
    stem = Path(rel).stem.lower()
    parts = Path(rel).parts
    score = 0
    reasons: list[str] = []

    if rel_lower in task_lower:
        score += 140
        reasons.append("task mentions path")
    elif basename in task_lower:
        score += 110
        reasons.append("task mentions filename")
    elif stem and stem in task_lower:
        score += 90
        reasons.append("task mentions stem")

    if _task_mentions_tests(task_lower):
        if "tests" in rel_lower or basename.startswith("test_") or basename.endswith("_test.py"):
            score += 140
            reasons.append("task mentions tests")

    if basename in _IMPORTANT_BASENAMES:
        score += 28
        reasons.append("important project file")

    if basename.startswith("config.") or basename.startswith("settings.") or basename.endswith((".toml", ".yaml", ".yml", ".json", ".ini")):
        score += 18
        reasons.append("config file")

    if basename.endswith(".py"):
        score += 14
        reasons.append("python source")
    elif basename.endswith((".md", ".rst")):
        score += 8
        reasons.append("documentation file")

    if parts and parts[0] == "tests":
        score += 16
        reasons.append("tests directory")

    for token in _task_tokens(task_lower):
        if len(token) < 3:
            continue
        if token == basename or token == stem:
            score += 35
            reasons.append(f"matched token {token}")
            break
        if token in rel_lower:
            score += 10
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
    return {directory for directory, score in by_dir.items() if score >= 70}


def _path_matches(rel_path: Path, pattern: str) -> bool:
    if rel_path.match(pattern):
        return True
    if pattern.startswith("**/") and rel_path.match(pattern[3:]):
        return True
    return False

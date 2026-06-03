from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FILE_TOKEN_RE = re.compile(r"(?P<path>(?:[A-Za-z]:[\\/])?[A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)")
_CREATE_HINT_RE = re.compile(
    r"\b(create|new|add|make)\b|созда(?:й|ть)|нов(?:ый|ую)\s+файл",
    flags=re.IGNORECASE,
)
_UPDATE_HINT_RE = re.compile(
    r"\b(update|fix|edit|modify)\b|исправ(?:ь|ить)|обнов(?:и|ить)|измени(?:ть)?",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskTarget:
    path: str
    mode: str
    exists: bool


def detect_task_target(task: str, workspace_root: Path) -> TaskTarget | None:
    workspace_root = workspace_root.resolve()
    candidates = _extract_candidate_paths(task, workspace_root)
    if not candidates:
        return None
    mode = _detect_mode(task)
    for candidate in candidates:
        resolved = (workspace_root / candidate).resolve()
        if resolved.exists():
            return TaskTarget(path=candidate, mode=mode, exists=True)
    return TaskTarget(path=candidates[0], mode=mode, exists=False)


def _extract_candidate_paths(task: str, workspace_root: Path) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for match in _FILE_TOKEN_RE.finditer(task):
        raw = match.group("path").strip().strip("\"'")
        normalized = _normalize_candidate(raw, workspace_root)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(normalized)
    return candidates


def _normalize_candidate(raw: str, workspace_root: Path) -> str | None:
    candidate = Path(raw)
    try:
        if candidate.is_absolute():
            resolved = candidate.resolve()
            try:
                return resolved.relative_to(workspace_root).as_posix()
            except ValueError:
                return None
        return Path(raw.replace("\\", "/")).as_posix()
    except OSError:
        return None


def _detect_mode(task: str) -> str:
    if _CREATE_HINT_RE.search(task):
        return "create"
    if _UPDATE_HINT_RE.search(task):
        return "update"
    return "unknown"

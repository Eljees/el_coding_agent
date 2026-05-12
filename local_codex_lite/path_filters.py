from __future__ import annotations

from pathlib import Path

BLOCKED_RUNTIME_DIRS = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".local-codex-lite",
    ".vscode",
    "__old",
    "generated_projects",
    "pytest_tmp",
    "scan_runs",
    "tmp_trufflehog",
    ".tmp",
)


def path_has_blocked_dir(path: Path | tuple[str, ...]) -> bool:
    parts = path.parts if isinstance(path, Path) else path
    return any(part in BLOCKED_RUNTIME_DIRS for part in parts)

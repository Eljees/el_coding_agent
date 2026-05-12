from __future__ import annotations

from pathlib import Path

from local_codex_lite.path_filters import BLOCKED_RUNTIME_DIRS, path_has_blocked_dir


def test_blocked_runtime_dirs_include_generated_and_runs() -> None:
    assert "generated_projects" in BLOCKED_RUNTIME_DIRS
    assert ".local-codex-lite" in BLOCKED_RUNTIME_DIRS
    assert "scan_runs" in BLOCKED_RUNTIME_DIRS


def test_path_has_blocked_dir_detects_nested_runtime_dir() -> None:
    assert path_has_blocked_dir(Path("src/.local-codex-lite/cache").parts) is True
    assert path_has_blocked_dir(Path("src/generated_projects/demo").parts) is True
    assert path_has_blocked_dir(Path("src/app").parts) is False

"""Additional coverage for ui_state.py and ui_runners.py — exception branches."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# ui_state.py:34-35 — save_geometry swallows exceptions
# ---------------------------------------------------------------------------


def test_save_geometry_swallows_write_exception(tmp_path: Path) -> None:
    from local_codex_lite.ui_state import save_geometry

    with patch("local_codex_lite.ui_state.Path.write_text", side_effect=OSError("disk full")):
        save_geometry(tmp_path, "800x600+0+0")


# ---------------------------------------------------------------------------
# ui_state.py:64-65 — save_task_history swallows exceptions
# ---------------------------------------------------------------------------


def test_save_task_history_swallows_write_exception(tmp_path: Path) -> None:
    from local_codex_lite.ui_state import save_task_history

    with patch("local_codex_lite.ui_state.Path.write_text", side_effect=OSError("disk full")):
        save_task_history(tmp_path, ["task1", "task2"])


# ---------------------------------------------------------------------------
# ui_runners.py:307 — appsechub_worker returns error on FileNotFoundError
# ---------------------------------------------------------------------------


def test_appsechub_worker_returns_error_when_python_not_found() -> None:
    from local_codex_lite.ui_runners import appsechub_worker

    with patch("subprocess.run", side_effect=FileNotFoundError("python not found")):
        result = appsechub_worker("проект 89 апсекхаб")
    assert "python executable not found" in result

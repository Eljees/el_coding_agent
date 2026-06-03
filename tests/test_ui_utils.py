"""Tests for the pure helpers in local_codex_lite.ui.

The full Tkinter command center is intentionally not exercised here -- it
needs a display, a real Tk root, and would dominate CI time.  Instead this
module locks down the behaviour of the small free functions and the
file-backed persistence helpers that don't require an actual Tk window.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from local_codex_lite import ui
from local_codex_lite.intent import IntentDecision

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task,expected",
    [
        ("scan the artifacts", "HIGH"),
        ("проверь на CVE", "HIGH"),
        ("include medium severity", "MEDIUM"),
        ("полный отчёт по CVE", "MEDIUM"),
        ("расширенный CVE-отчёт", "MEDIUM"),
        ("med severity findings", "MEDIUM"),
        ("включая medium severity", "MEDIUM"),
        ("начиная с medium severity", "MEDIUM"),
    ],
)
def test_cve_min_severity_for_task(task: str, expected: str) -> None:
    assert ui.cve_min_severity_for_task(task) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "00:00"),
        (1, "00:01"),
        (59, "00:59"),
        (60, "01:00"),
        (65, "01:05"),
        (3599, "59:59"),
        (3600, "60:00"),
        (-5, "00:00"),  # clamped to zero
        (12.7, "00:12"),  # floats truncated
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert ui.format_duration(seconds) == expected


def _decision(intent: str) -> IntentDecision:
    return IntentDecision(
        can_do="yes",
        intent=intent,
        confidence=0.9,
        human_summary="",
        safe_next_action="",
        required_inputs=(),
        missing_inputs=(),
        requires_apply=False,
        requires_exec=False,
        requires_external_help=False,
        risks=(),
        cli_equivalent="",
        capability_id=intent,
        matched_keywords=(),
    )


def test_should_create_project_workspace_true_for_creation_phrase() -> None:
    # No decision -- should_use_project_workspace gates on the task text.
    assert ui.should_create_project_workspace("создай новый GUI калькулятор") is True


def test_should_create_project_workspace_false_for_fix_phrase() -> None:
    assert ui.should_create_project_workspace("исправь баг в patcher.py") is False


def test_should_create_project_workspace_false_when_intent_not_run() -> None:
    # A creation-like task but routed to logs.latest must NOT create a
    # generated_projects/ folder.
    decision = _decision("logs.latest")
    assert ui.should_create_project_workspace("создай новый калькулятор", decision) is False


def test_should_create_project_workspace_true_for_run_preview_intent() -> None:
    decision = _decision("run.preview")
    assert ui.should_create_project_workspace("создай новый калькулятор", decision) is True


def test_temporary_cwd_restores_previous(tmp_path: Path) -> None:
    """The context manager must restore the original cwd even when the body
    raises -- otherwise a single failed background task would leave the GUI
    pointing into a generated_projects/ folder forever."""
    original = Path.cwd()
    try:
        with ui.temporary_cwd(tmp_path):
            assert Path.cwd().resolve() == tmp_path.resolve()
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert Path.cwd() == original


# ---------------------------------------------------------------------------
# File-backed persistence: task history + window geometry
#
# We don't instantiate CommandCenterUI (it needs a Tk root); instead we
# build a duck-typed fake `self` and invoke the unbound methods directly.
# This keeps the tests CI-friendly while still locking the read/write
# format that the GUI consumes.
# ---------------------------------------------------------------------------


def _fake_ui(tmp_path: Path) -> types.SimpleNamespace:
    """A duck-typed `self` for CommandCenterUI's file-backed methods.

    The methods we exercise call ``self._refresh_history_combo()`` after a
    write; we stub it to a no-op since the real implementation needs a
    Tk Combobox widget.
    """
    return types.SimpleNamespace(
        _base_workspace_root=tmp_path,
        _task_history=[],
        _refresh_history_combo=lambda *_args, **_kwargs: None,
    )


def test_load_task_history_returns_empty_when_file_missing(tmp_path: Path) -> None:
    fake = _fake_ui(tmp_path)
    fake._task_history = ["should be cleared"]
    ui.CommandCenterUI._load_task_history(fake)
    assert fake._task_history == []


def test_load_task_history_reads_existing_list(tmp_path: Path) -> None:
    hist = tmp_path / ".local-codex-lite" / "task_history.json"
    hist.parent.mkdir(parents=True)
    hist.write_text(json.dumps(["one", "two"]), encoding="utf-8")
    fake = _fake_ui(tmp_path)
    ui.CommandCenterUI._load_task_history(fake)
    assert fake._task_history == ["one", "two"]


def test_load_task_history_caps_at_history_max(tmp_path: Path) -> None:
    overflow = [f"task {i}" for i in range(ui._HISTORY_MAX + 25)]
    hist = tmp_path / ".local-codex-lite" / "task_history.json"
    hist.parent.mkdir(parents=True)
    hist.write_text(json.dumps(overflow), encoding="utf-8")
    fake = _fake_ui(tmp_path)
    ui.CommandCenterUI._load_task_history(fake)
    assert len(fake._task_history) == ui._HISTORY_MAX
    assert fake._task_history[0] == "task 0"


def test_load_task_history_ignores_non_list_payload(tmp_path: Path) -> None:
    hist = tmp_path / ".local-codex-lite" / "task_history.json"
    hist.parent.mkdir(parents=True)
    hist.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    fake = _fake_ui(tmp_path)
    ui.CommandCenterUI._load_task_history(fake)
    assert fake._task_history == []


def test_save_task_to_history_persists_and_dedupes(tmp_path: Path) -> None:
    fake = _fake_ui(tmp_path)
    # First save creates the file.
    ui.CommandCenterUI._save_task_to_history(fake, "task A")
    ui.CommandCenterUI._save_task_to_history(fake, "task B")
    # Repeating an old entry must move it to the front, not duplicate it.
    ui.CommandCenterUI._save_task_to_history(fake, "task A")
    assert fake._task_history == ["task A", "task B"]

    hist = tmp_path / ".local-codex-lite" / "task_history.json"
    payload = json.loads(hist.read_text(encoding="utf-8"))
    assert payload == ["task A", "task B"]


def test_save_task_to_history_ignores_empty_task(tmp_path: Path) -> None:
    fake = _fake_ui(tmp_path)
    ui.CommandCenterUI._save_task_to_history(fake, "")
    assert fake._task_history == []


def test_load_geometry_returns_none_when_missing(tmp_path: Path) -> None:
    fake = _fake_ui(tmp_path)
    assert ui.CommandCenterUI._load_geometry(fake) is None


def test_load_geometry_reads_existing(tmp_path: Path) -> None:
    geo = tmp_path / ".local-codex-lite" / "ui_geometry.txt"
    geo.parent.mkdir(parents=True)
    geo.write_text("1280x720+100+50\n", encoding="utf-8")
    fake = _fake_ui(tmp_path)
    assert ui.CommandCenterUI._load_geometry(fake) == "1280x720+100+50"


def test_load_geometry_returns_none_for_blank_file(tmp_path: Path) -> None:
    geo = tmp_path / ".local-codex-lite" / "ui_geometry.txt"
    geo.parent.mkdir(parents=True)
    geo.write_text("\n", encoding="utf-8")
    fake = _fake_ui(tmp_path)
    assert ui.CommandCenterUI._load_geometry(fake) is None


def test_save_geometry_writes_string_returned_by_root(tmp_path: Path) -> None:
    fake = types.SimpleNamespace(
        _base_workspace_root=tmp_path,
        root=types.SimpleNamespace(geometry=lambda: "1024x768+10+20"),
    )
    ui.CommandCenterUI._save_geometry(fake)
    geo = tmp_path / ".local-codex-lite" / "ui_geometry.txt"
    assert geo.read_text(encoding="utf-8") == "1024x768+10+20"

"""Unit tests for the Tk-free GUI persistence helpers (ui_state)."""

from __future__ import annotations

import json
from pathlib import Path

from local_codex_lite import ui_state


def test_geometry_roundtrip(tmp_path: Path) -> None:
    assert ui_state.load_geometry(tmp_path) is None  # nothing saved yet
    ui_state.save_geometry(tmp_path, "800x600+10+20")
    assert ui_state.load_geometry(tmp_path) == "800x600+10+20"


def test_geometry_blank_file_reads_as_none(tmp_path: Path) -> None:
    ui_state.save_geometry(tmp_path, "   ")
    assert ui_state.load_geometry(tmp_path) is None


def test_task_history_roundtrip(tmp_path: Path) -> None:
    assert ui_state.load_task_history(tmp_path) == []  # missing file
    ui_state.save_task_history(tmp_path, ["a", "b"])
    assert ui_state.load_task_history(tmp_path) == ["a", "b"]


def test_load_task_history_ignores_non_list(tmp_path: Path) -> None:
    (tmp_path / ui_state.HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ui_state.HISTORY_FILE).write_text('{"not": "a list"}', encoding="utf-8")
    assert ui_state.load_task_history(tmp_path) == []


def test_load_task_history_ignores_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / ui_state.HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ui_state.HISTORY_FILE).write_text("{not json", encoding="utf-8")
    assert ui_state.load_task_history(tmp_path) == []


def test_load_task_history_caps_length(tmp_path: Path) -> None:
    big = [str(i) for i in range(ui_state.HISTORY_MAX + 25)]
    (tmp_path / ui_state.HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ui_state.HISTORY_FILE).write_text(json.dumps(big), encoding="utf-8")
    assert len(ui_state.load_task_history(tmp_path)) == ui_state.HISTORY_MAX


def test_push_task_moves_to_front_and_dedupes() -> None:
    assert ui_state.push_task(["a", "b", "c"], "b") == ["b", "a", "c"]
    assert ui_state.push_task(["a"], "new") == ["new", "a"]


def test_push_task_empty_is_noop() -> None:
    assert ui_state.push_task(["a", "b"], "") == ["a", "b"]


def test_push_task_caps_length() -> None:
    history = [str(i) for i in range(ui_state.HISTORY_MAX)]
    result = ui_state.push_task(history, "newest")
    assert result[0] == "newest"
    assert len(result) == ui_state.HISTORY_MAX

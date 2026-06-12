"""Targeted tests for small coverage gaps across multiple modules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# capabilities.py:280 — capability_brief_lines
# ---------------------------------------------------------------------------


def test_capability_brief_lines_returns_id_title_pairs() -> None:
    from local_codex_lite.capabilities import capability_brief_lines, default_capabilities

    lines = capability_brief_lines(default_capabilities())
    assert any("run.preview" in line for line in lines)
    assert all(" - " in line for line in lines)


# ---------------------------------------------------------------------------
# tool_registry.py:125 — resolve_executor with no module component
# ---------------------------------------------------------------------------


def test_resolve_executor_raises_on_no_module_component() -> None:
    from local_codex_lite.tool_registry import resolve_executor

    with pytest.raises(AttributeError, match="no module component"):
        resolve_executor("just_attr_no_dot")


# ---------------------------------------------------------------------------
# tool_registry.py:132 — tool_brief_lines
# ---------------------------------------------------------------------------


def test_tool_brief_lines_returns_name_desc_pairs() -> None:
    from local_codex_lite.tool_registry import default_tools, tool_brief_lines

    lines = tool_brief_lines(default_tools())
    assert lines
    assert all(" - " in line for line in lines)


# ---------------------------------------------------------------------------
# project_workspace.py:59 — slugify_task with all-special chars
# ---------------------------------------------------------------------------


def test_slugify_task_all_special_chars_returns_task() -> None:
    from local_codex_lite.project_workspace import slugify_task

    assert slugify_task("!@#$%^&*()") == "task"


# ---------------------------------------------------------------------------
# project_workspace.py:84 — resolve_task_workspace with generated path
# ---------------------------------------------------------------------------


def test_resolve_task_workspace_returns_base_when_already_generated(tmp_path: Path) -> None:
    from local_codex_lite.project_workspace import resolve_task_workspace

    generated_root = tmp_path / "generated_projects" / "myproject"
    generated_root.mkdir(parents=True)
    result = resolve_task_workspace(generated_root, "fix a bug")
    assert result == generated_root


# ---------------------------------------------------------------------------
# project_workspace.py:87 — resolve_task_workspace creates project workspace
# ---------------------------------------------------------------------------


def test_resolve_task_workspace_creates_project_workspace(tmp_path: Path) -> None:
    from local_codex_lite.project_workspace import resolve_task_workspace

    result = resolve_task_workspace(tmp_path, "создай калькулятор на tkinter")
    assert "generated_projects" in result.parts
    assert result.is_dir()


# ---------------------------------------------------------------------------
# undo.py:53 — "destination outside workspace" skip reason
# ---------------------------------------------------------------------------


def test_collect_undo_entries_flags_destination_outside_workspace(tmp_path: Path) -> None:
    from local_codex_lite.undo import collect_undo_entries

    run_dir = tmp_path / "runs" / "20260601-120000"
    backups_dir = run_dir / "backups"
    backups_dir.mkdir(parents=True)
    backup_file = backups_dir / "foo.py"
    backup_file.write_text("content\n", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    from local_codex_lite import safety

    real_is_inside = safety.is_inside_workspace

    def patched_is_inside(path: Path, root: Path) -> bool:
        if path.name == "foo.py":
            return False
        return real_is_inside(path, root)

    with patch("local_codex_lite.undo.is_inside_workspace", side_effect=patched_is_inside):
        entries = collect_undo_entries(run_dir, workspace)

    assert entries
    assert entries[0].skip_reason == "destination outside workspace"


# ---------------------------------------------------------------------------
# undo.py:71-72 — cmd_undo with run_dir that has no backups
# ---------------------------------------------------------------------------


def test_cmd_undo_returns_1_when_run_has_no_backups(tmp_path: Path, monkeypatch) -> None:
    from local_codex_lite.undo import cmd_undo

    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260601-120000"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr("local_codex_lite.undo.workspace_root", lambda: tmp_path)
    rc = cmd_undo(argparse.Namespace(run="20260601-120000", apply=False))
    assert rc == 1


# ---------------------------------------------------------------------------
# run_report.py:155 — _as_int with bool returns default
# ---------------------------------------------------------------------------


def test_as_int_with_bool_returns_default() -> None:
    from local_codex_lite.run_report import _as_int

    assert _as_int(True, 99) == 99
    assert _as_int(False, 42) == 42


# ---------------------------------------------------------------------------
# run_report.py:178 — _code_and_detail with issue_type
# ---------------------------------------------------------------------------


def test_code_and_detail_uses_issue_type_when_no_patch_error() -> None:
    from local_codex_lite.run_report import _code_and_detail

    item = {"issue_type": "context_mismatch", "error": "patch failed"}
    code, detail = _code_and_detail(item)
    assert code == "context_mismatch"
    assert "patch failed" in detail


# ---------------------------------------------------------------------------
# run_report.py:183 — _code_and_detail with errors list
# ---------------------------------------------------------------------------


def test_code_and_detail_joins_errors_list() -> None:
    from local_codex_lite.run_report import _code_and_detail

    item = {"errors": ["line 1", "line 2"]}
    _code, detail = _code_and_detail(item)
    assert "line 1" in detail
    assert "line 2" in detail


# ---------------------------------------------------------------------------
# run_report.py:312-317 — _run_timestamp fallback for non-timestamp name
# ---------------------------------------------------------------------------


def test_run_timestamp_falls_back_to_mtime_for_non_timestamp_name(tmp_path: Path) -> None:
    from local_codex_lite.run_report import _run_timestamp

    run_dir = tmp_path / "custom-run-name"
    run_dir.mkdir()
    result = _run_timestamp(run_dir)
    assert result > 0


def test_run_timestamp_returns_zero_for_nonexistent_dir(tmp_path: Path) -> None:
    from local_codex_lite.run_report import _run_timestamp

    result = _run_timestamp(tmp_path / "nonexistent-dir")
    assert result == 0.0

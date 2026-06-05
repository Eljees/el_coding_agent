"""Unit tests for the Tk-free task heuristics extracted from ui.py.

The decision argument is duck-typed (only ``.intent`` is read), so a
SimpleNamespace stands in for an IntentDecision without importing the GUI.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from local_codex_lite import task_heuristics as th


@pytest.mark.parametrize(
    "task,expected",
    [
        (r"проверь на cve артефакт D:\artifacts\demo.rpm", "HIGH"),
        ("scan this build for vulnerabilities", "HIGH"),
        ("сделай полный cve отчёт включая medium", "MEDIUM"),
        ("нужен расширенный отчёт по cve", "MEDIUM"),
        ("a medium-depth report please", "MEDIUM"),
    ],
)
def test_cve_min_severity_for_task(task: str, expected: str) -> None:
    assert th.cve_min_severity_for_task(task) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "00:00"), (5, "00:05"), (65, "01:05"), (600, "10:00"), (-3, "00:00")],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert th.format_duration(seconds) == expected


def test_should_create_project_workspace_true_for_creation_phrase() -> None:
    assert th.should_create_project_workspace("создай новый GUI калькулятор") is True


def test_should_create_project_workspace_false_for_fix_phrase() -> None:
    assert th.should_create_project_workspace("исправь баг в patcher.py") is False


def test_should_create_project_workspace_false_when_intent_not_run() -> None:
    decision = types.SimpleNamespace(intent="evidence.cve_scan")
    assert th.should_create_project_workspace("создай новый калькулятор", decision) is False


def test_should_create_project_workspace_true_for_run_preview_intent() -> None:
    decision = types.SimpleNamespace(intent="run.preview")
    assert th.should_create_project_workspace("создай новый калькулятор", decision) is True


def test_temporary_cwd_changes_and_restores(tmp_path: Path) -> None:
    before = Path.cwd()
    with th.temporary_cwd(tmp_path):
        assert Path.cwd() == tmp_path.resolve()
    assert Path.cwd() == before

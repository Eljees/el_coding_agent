"""Tests for ``local_codex_lite.ui_commands``.

All tests are Tkinter-free: the module holds the GUI's dispatch, formatting
and button-state logic extracted from ``ui.py`` precisely so it can be
exercised without a display.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_codex_lite.capabilities import Capability
from local_codex_lite.intent import IntentDecision
from local_codex_lite.skill_registry import SkillDefinition
from local_codex_lite.tool_registry import ToolDefinition
from local_codex_lite.ui_commands import (
    BackgroundAction,
    action_button_states,
    action_for_apply,
    action_for_exec,
    action_for_preview,
    analyze_completed_message,
    append_output,
    capability_detail_text,
    combined_copy_text,
    decision_json,
    decision_status_labels,
    export_output_text,
    finalize_run_output,
    heartbeat_message,
    history_labels,
    is_preview_ready,
    skill_detail_text,
    tool_detail_text,
    workspace_status,
)


def _decision(
    intent: str,
    *,
    can_do: str = "yes",
    requires_exec: bool = False,
    missing_inputs: tuple[str, ...] = (),
) -> IntentDecision:
    return IntentDecision(
        can_do=can_do,
        intent=intent,
        confidence=0.9,
        human_summary="summary",
        safe_next_action="run preview",
        required_inputs=(),
        missing_inputs=missing_inputs,
        requires_apply=True,
        requires_exec=requires_exec,
        requires_external_help=False,
        risks=(),
        cli_equivalent="local-codex-lite run",
        capability_id=intent,
        matched_keywords=(),
    )


# ---------------------------------------------------------------------------
# Background action dispatch
# ---------------------------------------------------------------------------


def test_action_for_preview_artifact_intent() -> None:
    action = action_for_preview("evidence.artifacts.inspect")
    assert action == BackgroundAction(label="artifacts inspect", kind="artifact", extract=False)


def test_action_for_preview_cve_intent() -> None:
    action = action_for_preview("evidence.cve_scan")
    assert action.label == "cve scan"
    assert action.kind == "cve"


def test_action_for_preview_appsechub_intent() -> None:
    action = action_for_preview("appsechub.issues")
    assert action.label == "appsechub breakdown"
    assert action.kind == "appsechub"


def test_action_for_preview_default_is_preview() -> None:
    action = action_for_preview("run.preview")
    assert action == BackgroundAction(label="preview", kind="preview")


def test_action_for_apply_artifact_intent_extracts() -> None:
    action = action_for_apply("evidence.artifacts.inspect")
    assert action == BackgroundAction(label="artifacts extract", kind="artifact", extract=True)


def test_action_for_apply_cve_intent() -> None:
    action = action_for_apply("evidence.cve_scan")
    assert action.label == "cve scan"
    assert action.kind == "cve"


def test_action_for_apply_default_runs_apply_without_exec() -> None:
    action = action_for_apply("run.apply")
    assert action.label == "apply"
    assert action.kind == "run"
    assert action.apply is True
    assert action.exec_ is False


def test_action_for_exec_runs_apply_and_exec() -> None:
    action = action_for_exec()
    assert action.label == "apply + exec"
    assert action.kind == "run"
    assert action.apply is True
    assert action.exec_ is True


# ---------------------------------------------------------------------------
# Decision panel formatting
# ---------------------------------------------------------------------------


def test_decision_status_labels_without_missing_inputs() -> None:
    labels = decision_status_labels(_decision("run.preview"))
    assert labels == (
        "can do: yes",
        "requires apply: True",
        "requires exec: False",
        "missing inputs: -",
        "safe next action: run preview",
    )


def test_decision_status_labels_joins_missing_inputs() -> None:
    labels = decision_status_labels(_decision("run.preview", missing_inputs=("task", "evidence")))
    assert labels[3] == "missing inputs: task, evidence"


def test_decision_json_round_trips() -> None:
    text = decision_json(_decision("run.preview"))
    data = json.loads(text)
    assert data["intent"] == "run.preview"
    assert data["can_do"] == "yes"


def test_analyze_completed_message_prefixes_json() -> None:
    message = analyze_completed_message(_decision("run.preview"))
    assert message.startswith("Intent analysis completed in-process.\n\n")
    assert '"intent": "run.preview"' in message


# ---------------------------------------------------------------------------
# Detail panel formatting
# ---------------------------------------------------------------------------


def test_capability_detail_text_lists_fields_and_examples() -> None:
    capability = Capability(
        id="cap.demo",
        title="Demo capability",
        description="Does demo things.",
        examples=("example one", "example two"),
        keywords=("demo",),
        required_inputs=(),
        safety_level="read_only",
        requires_apply=False,
        requires_exec=True,
        cli_equivalent="local-codex-lite demo",
    )
    text = capability_detail_text(capability)
    assert "id: cap.demo" in text
    assert "title: Demo capability" in text
    assert "safety: read_only" in text
    assert "requires_apply: False" in text
    assert "requires_exec: True" in text
    assert "- example one" in text
    assert "- example two" in text
    assert text.endswith("cli:\nlocal-codex-lite demo")


def test_tool_detail_text_includes_schema_json() -> None:
    tool = ToolDefinition(
        name="read_file",
        description="Read a file.",
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
        executor="local",
        safety_level="read_only",
        requires_exec=False,
    )
    text = tool_detail_text(tool)
    assert "name: read_file" in text
    assert "safety: read_only" in text
    assert "executor: local" in text
    assert '"type": "object"' in text


def test_skill_detail_text_includes_path_and_summary(tmp_path: Path) -> None:
    skill = SkillDefinition(name="demo-skill", path=tmp_path, summary="A demo skill.")
    text = skill_detail_text(skill)
    assert "name: demo-skill" in text
    assert f"path: {tmp_path}" in text
    assert text.endswith("summary:\nA demo skill.")


# ---------------------------------------------------------------------------
# Button states
# ---------------------------------------------------------------------------


def test_action_button_states_disabled_when_busy() -> None:
    states = action_button_states(
        busy=True, decision=_decision("evidence.cve_scan"), preview_ready=True
    )
    assert states == ("disabled", "disabled")


def test_action_button_states_disabled_without_decision() -> None:
    assert action_button_states(busy=False, decision=None, preview_ready=True) == (
        "disabled",
        "disabled",
    )


@pytest.mark.parametrize("intent", ["evidence.artifacts.inspect", "evidence.cve_scan"])
def test_action_button_states_evidence_intents_enable_apply(intent: str) -> None:
    apply_state, exec_state = action_button_states(
        busy=False, decision=_decision(intent), preview_ready=False
    )
    assert apply_state == "normal"
    assert exec_state == "disabled"


@pytest.mark.parametrize("intent", ["evidence.artifacts.inspect", "evidence.cve_scan"])
def test_action_button_states_evidence_intents_need_can_do_yes(intent: str) -> None:
    apply_state, _ = action_button_states(
        busy=False, decision=_decision(intent, can_do="no"), preview_ready=False
    )
    assert apply_state == "disabled"


def test_action_button_states_run_intent_needs_preview_ready() -> None:
    decision = _decision("run.apply")
    assert action_button_states(busy=False, decision=decision, preview_ready=False) == (
        "disabled",
        "disabled",
    )
    apply_state, _ = action_button_states(busy=False, decision=decision, preview_ready=True)
    assert apply_state == "normal"


def test_action_button_states_exec_enabled_for_run_exec_intent() -> None:
    _, exec_state = action_button_states(
        busy=False, decision=_decision("run.exec"), preview_ready=True
    )
    assert exec_state == "normal"


def test_action_button_states_exec_enabled_when_decision_requires_exec() -> None:
    _, exec_state = action_button_states(
        busy=False,
        decision=_decision("run.apply", requires_exec=True),
        preview_ready=True,
    )
    assert exec_state == "normal"


# ---------------------------------------------------------------------------
# Output post-processing
# ---------------------------------------------------------------------------


def test_finalize_run_output_appends_duration_footer() -> None:
    result = finalize_run_output("  patch preview ok  \n", 65.0)
    assert result == "patch preview ok\n\ncompleted in 01:05"


def test_finalize_run_output_keeps_empty_output_empty() -> None:
    assert finalize_run_output("", 10.0) == ""


def test_finalize_run_output_appends_workspace_path() -> None:
    from pathlib import Path

    result = finalize_run_output("done", 5.0, workspace=Path("D:/proj/ws"))
    assert result.endswith(f"results in: {Path('D:/proj/ws')}")
    # empty output stays empty even with a workspace
    assert finalize_run_output("", 5.0, workspace=Path("D:/proj/ws")) == ""


@pytest.mark.parametrize(
    "output,expected",
    [
        ("PATCH PREVIEW OK", True),
        ("the patch applied cleanly", True),
        ("Run completed successfully", True),
        ("something failed", False),
        ("", False),
    ],
)
def test_is_preview_ready(output: str, expected: bool) -> None:
    assert is_preview_ready(output) is expected


def test_heartbeat_message_formats_elapsed() -> None:
    assert heartbeat_message(125) == "still running: 02:05"


def test_append_output_to_empty_cache() -> None:
    assert append_output("", "line") == "line"


def test_append_output_joins_with_newline() -> None:
    assert append_output("first", "second") == "first\nsecond"


def test_combined_copy_text_with_both_parts() -> None:
    combined = combined_copy_text('{"a": 1}', "done")
    assert combined == 'IntentDecision JSON:\n{"a": 1}\n\nCommand output:\ndone'


def test_combined_copy_text_with_only_command_output() -> None:
    assert combined_copy_text("", "done") == "Command output:\ndone"


def test_combined_copy_text_with_only_intent_json() -> None:
    assert combined_copy_text("{}", "") == "IntentDecision JSON:\n{}"


def test_combined_copy_text_empty_when_both_empty() -> None:
    assert combined_copy_text("", "") == ""


def test_export_output_text_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "output.txt"
    assert export_output_text(str(target), "exported text") is None
    assert target.read_text(encoding="utf-8") == "exported text"


def test_export_output_text_returns_error_line_on_failure(tmp_path: Path) -> None:
    # Writing into a missing directory must fail and produce the panel line.
    target = tmp_path / "no_such_dir" / "output.txt"
    error = export_output_text(str(target), "exported text")
    assert error is not None
    assert error.startswith("\nExport failed: ")


# ---------------------------------------------------------------------------
# Misc labels
# ---------------------------------------------------------------------------


def test_workspace_status_label(tmp_path: Path) -> None:
    assert workspace_status(tmp_path) == f"workspace: {tmp_path}"


def test_history_labels_uses_first_line_capped() -> None:
    history = ["short task", "first line\nsecond line", "x" * 200, ""]
    labels = history_labels(history)
    assert labels[0] == "short task"
    assert labels[1] == "first line"
    assert labels[2] == "x" * 120
    assert labels[3] == ""

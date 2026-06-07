"""Tk-free command/presentation helpers for the GUI command center.

Extracted from ``ui.py`` so the intent dispatch, label formatting, button-state
logic and output post-processing can be unit-tested without a display.  Each
function accepts plain Python values and returns strings / small dataclasses;
``CommandCenterUI`` only feeds widget contents in and pushes the results back
into widgets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .intent import IntentDecision, decision_as_dict
from .logging_utils import resolve_run_dir
from .run_report import build_attempt_timeline, list_run_dirs, render_timeline
from .task_heuristics import format_duration

if TYPE_CHECKING:  # imported lazily by the GUI; keep runtime deps minimal
    from .capabilities import Capability
    from .skill_registry import SkillDefinition
    from .tool_registry import ToolDefinition

# Intents that route the Apply button to the artifact / CVE evidence workers
# instead of the patch pipeline.
_PREVIEW_READY_INTENTS = {"run.preview", "run.apply", "run.exec"}


# ---------------------------------------------------------------------------
# Background action dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackgroundAction:
    """A background job selected for an intent.

    ``label`` is the progress label shown in the output panel; ``kind`` selects
    the worker (``artifact`` / ``cve`` / ``preview`` / ``run``) and the flags
    parametrise it.
    """

    label: str
    kind: str
    extract: bool = False
    apply: bool = False
    exec_: bool = False


def action_for_preview(intent: str) -> BackgroundAction:
    """Pick the background job for the Preview button based on *intent*."""
    if intent == "evidence.artifacts.inspect":
        return BackgroundAction(label="artifacts inspect", kind="artifact", extract=False)
    if intent == "evidence.cve_scan":
        return BackgroundAction(label="cve scan", kind="cve")
    if intent == "appsechub.issues":
        return BackgroundAction(label="appsechub breakdown", kind="appsechub")
    return BackgroundAction(label="preview", kind="preview")


def action_for_apply(intent: str) -> BackgroundAction:
    """Pick the background job for the Apply button based on *intent*."""
    if intent == "evidence.artifacts.inspect":
        return BackgroundAction(label="artifacts extract", kind="artifact", extract=True)
    if intent == "evidence.cve_scan":
        return BackgroundAction(label="cve scan", kind="cve")
    return BackgroundAction(label="apply", kind="run", apply=True, exec_=False)


def action_for_exec() -> BackgroundAction:
    """The background job for the Exec button (always apply + exec)."""
    return BackgroundAction(label="apply + exec", kind="run", apply=True, exec_=True)


# ---------------------------------------------------------------------------
# Decision panel formatting
# ---------------------------------------------------------------------------


def decision_status_labels(decision: IntentDecision) -> tuple[str, str, str, str, str]:
    """Format the five decision-panel labels for *decision*."""
    return (
        f"can do: {decision.can_do}",
        f"requires apply: {decision.requires_apply}",
        f"requires exec: {decision.requires_exec}",
        f"missing inputs: {', '.join(decision.missing_inputs) if decision.missing_inputs else '-'}",
        f"safe next action: {decision.safe_next_action}",
    )


def decision_json(decision: IntentDecision) -> str:
    """Render *decision* as the pretty JSON shown in the IntentDecision panel."""
    return json.dumps(decision_as_dict(decision), ensure_ascii=False, indent=2)


def analyze_completed_message(decision: IntentDecision) -> str:
    """The command-output text shown after an in-process intent analysis."""
    return "Intent analysis completed in-process.\n\n" + decision_json(decision)


# ---------------------------------------------------------------------------
# Detail panel formatting
# ---------------------------------------------------------------------------


def capability_detail_text(capability: Capability) -> str:
    """Multi-line detail text for a capability selected in the right panel."""
    lines = [
        f"id: {capability.id}",
        f"title: {capability.title}",
        f"safety: {capability.safety_level}",
        f"requires_apply: {capability.requires_apply}",
        f"requires_exec: {capability.requires_exec}",
        "",
        "description:",
        capability.description,
        "",
        "examples:",
    ]
    lines.extend(f"- {item}" for item in capability.examples)
    lines.extend(["", "cli:", capability.cli_equivalent])
    return "\n".join(lines)


def tool_detail_text(tool: ToolDefinition) -> str:
    """Multi-line detail text for a tool selected in the right panel."""
    lines = [
        f"name: {tool.name}",
        f"safety: {tool.safety_level}",
        f"requires_exec: {tool.requires_exec}",
        f"executor: {tool.executor}",
        "",
        "description:",
        tool.description,
        "",
        "schema:",
        json.dumps(tool.schema, ensure_ascii=False, indent=2),
    ]
    return "\n".join(lines)


def skill_detail_text(skill: SkillDefinition) -> str:
    """Multi-line detail text for a skill selected in the right panel."""
    lines = [
        f"name: {skill.name}",
        f"path: {skill.path}",
        "",
        "summary:",
        skill.summary,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Button states
# ---------------------------------------------------------------------------


def action_button_states(
    *,
    busy: bool,
    decision: IntentDecision | None,
    preview_ready: bool,
) -> tuple[str, str]:
    """Compute ``(apply_state, exec_state)`` Tk widget states.

    Pure translation of the enable/disable rules: evidence intents unlock Apply
    as soon as the decision says "yes"; run intents additionally require a
    successful preview, and Exec also needs the intent to demand execution.
    """
    apply_state = "disabled"
    exec_state = "disabled"
    if not busy and decision is not None:
        if (
            (decision.intent == "evidence.artifacts.inspect" and decision.can_do == "yes")
            or (decision.intent == "evidence.cve_scan" and decision.can_do == "yes")
            or (preview_ready and decision.intent in _PREVIEW_READY_INTENTS)
        ):
            apply_state = "normal"
        if preview_ready and (decision.intent == "run.exec" or decision.requires_exec):
            exec_state = "normal"
    return apply_state, exec_state


# ---------------------------------------------------------------------------
# Output post-processing
# ---------------------------------------------------------------------------


def finalize_run_output(
    output: str,
    elapsed_seconds: float,
    workspace: Path | None = None,
) -> str:
    """Strip *output*, append the ``completed in MM:SS`` footer and the workspace path.

    The workspace line answers the perennial "а куда он это сделал?" -- every
    finished job tells the user where to look for its results.
    """
    if output:
        output = output.strip()
        output = output + f"\n\ncompleted in {format_duration(elapsed_seconds)}"
        if workspace is not None:
            output = output + f"\nresults in: {workspace}"
    return output


def is_preview_ready(output: str) -> bool:
    """Whether a finished run's *output* unlocks the Apply/Exec buttons."""
    lower = output.lower()
    return "patch preview ok" in lower or "patch applied" in lower or "run completed" in lower


_CLARIFICATION_MARKER = "Plan needs clarification."


def extract_clarifying_questions(output: str) -> list[str]:
    """Parse the clarifying questions out of a captured run/preview *output*.

    The runner prints ``Plan needs clarification.`` followed by one ``- ...``
    line per question.  Returns the questions of the last such block, or an
    empty list when the run did not stop for clarification.
    """
    questions: list[str] = []
    in_block = False
    for line in output.splitlines():
        stripped = line.strip()
        if _CLARIFICATION_MARKER in stripped:
            in_block = True
            questions = []
            continue
        if not in_block:
            continue
        if stripped.startswith("- "):
            questions.append(stripped[2:].strip())
        elif stripped:
            in_block = False
    return questions


def clarification_evidence_block(qa_pairs: list[tuple[str, str]]) -> str:
    """Render *qa_pairs* as an evidence block the planner treats as ground truth."""
    lines = ["Clarification answers:"]
    for question, answer in qa_pairs:
        lines.append(f"Q: {question}")
        lines.append(f"A: {answer}")
    return "\n".join(lines)


def heartbeat_message(elapsed_seconds: float) -> str:
    """The periodic ``still running`` line appended while a worker is busy."""
    return f"still running: {format_duration(elapsed_seconds)}"


def append_output(existing: str, content: str) -> str:
    """Join *content* onto *existing* command output with a newline separator."""
    combined = existing
    if combined:
        combined += "\n"
    combined += content
    return combined


def combined_copy_text(intent_json: str, command_output: str) -> str:
    """Build the "Copy all" clipboard payload from the two output caches."""
    return "\n\n".join(
        part
        for part in (
            "IntentDecision JSON:\n" + intent_json if intent_json else "",
            "Command output:\n" + command_output if command_output else "",
        )
        if part
    )


def export_output_text(path: str, content: str) -> str | None:
    """Write *content* to *path*; return the error line for the panel or None."""
    try:
        Path(path).write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"\nExport failed: {exc}"
    return None


# ---------------------------------------------------------------------------
# Runs tab
# ---------------------------------------------------------------------------

_RUNS_OVERVIEW_LIMIT = 30


@dataclass(frozen=True)
class RunsOverview:
    """Listbox payload for the Runs tab: parallel run ids and display lines."""

    run_ids: tuple[str, ...]
    lines: tuple[str, ...]


def runs_overview(workspace_root: Path, limit: int = _RUNS_OVERVIEW_LIMIT) -> RunsOverview:
    """Summarize the most recent runs of *workspace_root*, newest first."""
    run_ids: list[str] = []
    lines: list[str] = []
    for run_dir in list_run_dirs(workspace_root, limit=limit):
        report = build_attempt_timeline(run_dir)
        run_ids.append(report.run_id)
        lines.append(f"{report.run_id}  [{report.final_status}]  {report.task_excerpt}".rstrip())
    return RunsOverview(run_ids=tuple(run_ids), lines=tuple(lines))


def runs_overview_lines(workspace_root: Path, limit: int = _RUNS_OVERVIEW_LIMIT) -> list[str]:
    """The Runs-tab listbox lines (id + final status + task excerpt)."""
    return list(runs_overview(workspace_root, limit=limit).lines)


def run_timeline_text(workspace_root: Path, run_id: str) -> str:
    """The attempt-timeline text shown when a run is selected in the Runs tab."""
    run_dir = resolve_run_dir(Path(workspace_root), run_id)
    if run_dir is None:
        return f"Run not found: {run_id}"
    return render_timeline(build_attempt_timeline(run_dir))


# ---------------------------------------------------------------------------
# Misc labels
# ---------------------------------------------------------------------------


def workspace_status(root: Path) -> str:
    """The status-bar label for the active workspace root."""
    return f"workspace: {root}"


def history_labels(history: list[str]) -> list[str]:
    """Combo-box labels for the task history: first line of each task, capped."""
    return [t.splitlines()[0][:120] if t else "" for t in history]

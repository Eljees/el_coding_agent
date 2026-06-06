"""Tk-free worker functions for the GUI's background threads.

Each function encapsulates a CLI invocation pattern:

- accepts plain Python values (task, workspace_root, evidence_text)
- returns a string result to be displayed in the command output panel
- has **no Tkinter dependency** → unit-testable without a display

``CommandCenterUI`` delegates to these functions so the business logic
can be exercised independently from the GUI event loop.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

from .intent import extract_artifact_input_path, extract_artifact_output_path
from .task_heuristics import cve_min_severity_for_task, temporary_cwd


@contextlib.contextmanager
def redirect_optional_stdin(evidence_text: str):  # type: ignore[return]
    """Temporarily replace ``sys.stdin`` with an in-memory string.

    When *evidence_text* is non-empty the context manager patches ``sys.stdin``
    so CLI commands that read from stdin receive the evidence text.  When it is
    empty the context manager is a no-op, leaving stdin untouched.
    """
    if not evidence_text:
        yield
        return
    previous = sys.stdin
    sys.stdin = io.StringIO(evidence_text)
    try:
        yield
    finally:
        sys.stdin = previous


def initial_progress_message(label: str, task: str, workspace_root: Path) -> str:
    """Build the startup message shown in the command output panel."""
    lines = [f"Running {label}...", f"Workspace: {workspace_root}"]
    if label == "cve scan":
        input_root = extract_artifact_input_path(task)
        extract_to = extract_artifact_output_path(task)
        severity = cve_min_severity_for_task(task)
        lines.extend(
            [
                "CVE scan started.",
                f"input={input_root or '-'}",
                f"min_severity={severity}",
                f"extract_to={extract_to or 'default beside artifact'}",
                "stage=resolve input",
                "stage=unpack artifacts if needed",
                "stage=run cve-bin-tool",
                "stage=write evidence and reports",
                "cve-bin-tool will run next; this can take several minutes.",
            ]
        )
    return "\n".join(lines)


def _capture(
    fn,
    args: argparse.Namespace,
    workspace_root: Path,
    evidence_text: str = "",
) -> tuple[str, int | None]:
    """Run *fn(args)* with stdout/stderr captured and cwd set to *workspace_root*.

    Returns ``(output, returncode)`` where *output* is stripped captured text.
    """
    buffer = io.StringIO()
    with (
        temporary_cwd(workspace_root),
        contextlib.redirect_stdout(buffer),
        contextlib.redirect_stderr(buffer),
        redirect_optional_stdin(evidence_text),
    ):
        code = fn(args)
    return buffer.getvalue().strip(), code


def _fmt(output: str, code: int | None, verb: str) -> str:
    """Format the captured *output* + exit code into a user-facing string."""
    if output:
        return output + (f"\n\n(exit code: {code})" if code else "")
    return f"{verb} finished with exit code {code}"


def preview_worker(task: str, workspace_root: Path, evidence_text: str) -> str:
    """Run ``cli.cmd_preview`` in *workspace_root* and return captured output."""
    from . import cli as cli_module

    args = argparse.Namespace(
        task=task, evidence_file=[], evidence_stdin=bool(evidence_text), rag=False
    )
    output, code = _capture(cli_module.cmd_preview, args, workspace_root, evidence_text)
    return _fmt(output, code, "Preview")


def logs_latest_worker(workspace_root: Path) -> str:
    """Run ``cli.cmd_logs_latest`` and return captured output."""
    from . import cli as cli_module

    output, code = _capture(cli_module.cmd_logs_latest, argparse.Namespace(), workspace_root)
    return _fmt(output, code, "Logs latest")


def artifact_worker(task: str, workspace_root: Path, *, extract: bool) -> str:
    """Inventory (and optionally extract) archives; return captured output."""
    from . import cli as cli_module

    input_root = extract_artifact_input_path(task)
    if not input_root:
        return "Artifact input path not found in task."
    extract_to = extract_artifact_output_path(task)
    args = argparse.Namespace(
        input_root=input_root,
        extract_to=extract_to or None,
        extract_to_flag=None,
        extract=extract,
        max_depth=2,
        max_files=2000,
        max_total_bytes=500_000_000,
    )
    output, code = _capture(cli_module.cmd_evidence_artifacts_inspect, args, workspace_root)
    return _fmt(output, code, "Artifact inspection")


def cve_worker(task: str, workspace_root: Path) -> str:
    """Run a CVE scan via ``cli.cmd_evidence_cve_scan``; return captured output."""
    from . import cli as cli_module

    input_root = extract_artifact_input_path(task)
    if not input_root:
        return "CVE scan input path not found in task."
    extract_to = extract_artifact_output_path(task)
    severity = cve_min_severity_for_task(task)
    args = argparse.Namespace(
        action_or_input=input_root,
        input_root=None,
        extract_to=extract_to or None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=False,
        min_severity=severity,
        format="json,md,high-critical-md",
    )
    output, code = _capture(cli_module.cmd_evidence_cve_scan, args, workspace_root)
    return _fmt(output, code, "CVE scan")


def run_worker(
    task: str,
    workspace_root: Path,
    evidence_text: str,
    *,
    apply: bool,
    exec_: bool,
) -> str:
    """Run the full agent pipeline (plan → patch → [apply] → [exec])."""
    from . import cli as cli_module

    args = argparse.Namespace(
        task=task,
        dry_run=False,
        apply=apply,
        exec=exec_,
        assume_clarification=True,
        evidence_file=[],
        evidence_stdin=bool(evidence_text),
    )
    output, code = _capture(
        lambda a: cli_module._run_task(task, a), args, workspace_root, evidence_text
    )
    return _fmt(output, code, "Run")

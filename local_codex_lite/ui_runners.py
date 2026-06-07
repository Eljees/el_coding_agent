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
import re
import sys
from pathlib import Path

from .intent import extract_artifact_input_path, extract_artifact_output_path
from .task_heuristics import cve_min_severity_for_task, temporary_cwd

# System prompt for the Chat tab's LLM conversation.
CHAT_SYSTEM_PROMPT = (
    "You are a helpful coding assistant embedded in a local agent tool. "
    "Answer questions about the code, tasks, and evidence concisely and accurately. "
    "Do not generate patches unless explicitly asked."
)


@contextlib.contextmanager
def redirect_optional_stdin(evidence_text: str):
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
    smoke: bool = False,
) -> str:
    """Run the full agent pipeline (plan → patch → [apply] → [exec] → [smoke])."""
    from . import cli as cli_module

    args = argparse.Namespace(
        task=task,
        dry_run=False,
        apply=apply,
        execute=exec_,  # runner.py reads args.execute (dest of --exec flag)
        smoke=smoke,
        assume_clarification=True,
        evidence_file=[],
        evidence_stdin=bool(evidence_text),
    )
    output, code = _capture(
        lambda a: cli_module._run_task(task, a), args, workspace_root, evidence_text
    )
    return _fmt(output, code, "Run")


def chat_worker(messages: list[dict[str, str]], workspace_root: Path) -> str:
    """Send the chat *messages* to the configured LLM and return the answer.

    Any failure (missing config, unreachable endpoint, ...) is rendered as an
    ``[Error: ...]`` line so the GUI can display it inline instead of crashing.
    """
    try:
        from .config import load_config
        from .llm_client import OpenAICompatibleClient

        cfg = load_config(workspace_root)
        client = OpenAICompatibleClient(cfg.llm)
        full_messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            *messages,
        ]
        response = client.chat(full_messages, max_tokens=1024)
        return response.text.strip()
    except Exception as exc:
        return f"[Error: {exc}]"


# Application reference inside a task: full appprofile URL or "проект(а) 89".
_APPSECHUB_URL_RE = re.compile(r"https?://\S*appprofile/\d+\S*", re.IGNORECASE)
_APPSECHUB_ID_RE = re.compile(r"(?:проект[ауе]?|app|приложени[ея])\s*[№#]?\s*(\d+)", re.IGNORECASE)


def extract_appsechub_app(task: str) -> str:
    """Pull an AppSecHub application reference (URL or numeric id) out of *task*."""
    m = _APPSECHUB_URL_RE.search(task)
    if m:
        return m.group(0).rstrip(".,;)")
    m = _APPSECHUB_ID_RE.search(task)
    if m:
        return m.group(1)
    return ""


def appsechub_skill_path() -> Path:
    """Path to the appsechub skill client inside this agent's repository."""
    return Path(__file__).resolve().parents[1] / "skills" / "appsechub" / "appsechub_client.py"


_TREND_RE = re.compile(
    r"\b(trend|тренд|delta|дельт|динам|dynamic|сравн|compar)",
    re.IGNORECASE,
)
# Scan IDs are typically 3+ digit numbers distinct from app IDs in the same task.
_SCAN_IDS_RE = re.compile(r"\b(\d{3,})\b")


def _appsechub_cmd(task: str, app: str) -> list[str]:
    """Choose the appsechub_client subcommand based on task keywords.

    * trend/compare keywords + ≥2 numeric IDs → ``trend --scans id1,id2,...``
    * trend/compare keywords only              → ``scans`` (list what's available)
    * secrets/trufflehog                       → ``breakdown --source trufflehog``
    * default                                  → ``breakdown``
    """
    skill = str(appsechub_skill_path())
    lowered = task.lower()
    base = [sys.executable, skill]

    if _TREND_RE.search(lowered):
        # Extract all 3+-digit numbers; the first one is likely the app id,
        # remaining ones are scan ids.
        all_ids = _SCAN_IDS_RE.findall(task)
        # Filter out the app id itself (exact string match)
        scan_ids = [n for n in all_ids if n != str(app)]
        if len(scan_ids) >= 2:
            return [*base, "trend", app, "--scans", ",".join(scan_ids[:10])]
        # Not enough scan IDs: list scans so the user can pick
        return [*base, "scans", app]

    cmd = [*base, "breakdown", app]
    if "trufflehog" in lowered or "трюфел" in lowered or "секрет" in lowered:
        cmd += ["--source", "trufflehog"]
    return cmd


def appsechub_worker(task: str) -> str:
    """Run a read-only AppSecHub query for the application named in *task*.

    Routes to breakdown, trend, or scans depending on task keywords.
    Delegates to the ``appsechub`` skill client in a subprocess so the GUI
    needs neither ``requests`` imported in-process nor the skill on ``sys.path``.
    """
    import subprocess

    app = extract_appsechub_app(task)
    if not app:
        return (
            "AppSecHub: could not find an application reference in the task.\n"
            "Paste the appprofile URL (https://.../#/appprofile/<id>/issues) "
            "or write e.g. 'проект 89'."
        )
    cmd = _appsechub_cmd(task, app)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        return "AppSecHub: python executable not found for the skill subprocess."
    except subprocess.TimeoutExpired:
        return "AppSecHub: query timed out (10 min)."
    output = (r.stdout or "").strip() or (r.stderr or "").strip()
    if r.returncode != 0:
        return f"AppSecHub query failed (exit {r.returncode}):\n{output}"
    return output


def probe_cve_status() -> str:
    """Return the one-line cve-bin-tool availability status for the status bar."""
    import subprocess as _sp

    try:
        r = _sp.run(
            ["cve-bin-tool", "--version"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        ver = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
        return f"cve-bin-tool: {ver}" if ver else "cve-bin-tool: ok"
    except FileNotFoundError:
        return "cve-bin-tool: not found"
    except Exception:
        return "cve-bin-tool: error"


def probe_llm_status(base_root: Path) -> str:
    """Return the one-line LLM endpoint reachability status for the status bar."""
    import urllib.request as _ur

    base_url = "http://localhost:8015/v1"
    try:
        from .config import load_config

        cfg = load_config(base_root)
        base_url = cfg.llm.base_url
    except Exception:
        pass
    try:
        _ur.urlopen(base_url.rstrip("/") + "/models", timeout=4)
        return f"LLM: {base_url} ok"
    except Exception:
        return f"LLM: {base_url} (unreachable)"

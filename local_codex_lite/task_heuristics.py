"""Pure, Tk-free task heuristics extracted from ``ui.py``.

These domain helpers decide project-workspace routing and CVE severity, and
provide small formatting / working-directory utilities.  Keeping them out of the
Tkinter god-class makes them unit-testable and reusable outside the GUI.

``ui.py`` re-imports every name defined here, so existing call sites and tests
that do ``from local_codex_lite.ui import cve_min_severity_for_task`` (etc.)
keep working unchanged.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .project_workspace import should_use_project_workspace

if TYPE_CHECKING:  # avoid importing the intent module at runtime
    from .intent import IntentDecision

# Intents for which a "create a new project" task should be routed into its own
# dated workspace rather than the agent's own repo.
_RUN_INTENTS = {"run.preview", "run.apply", "run.exec"}


def should_create_project_workspace(
    task: str, decision: IntentDecision | None = None
) -> bool:
    """Whether a task should run in a fresh project workspace.

    Only "run"-style intents qualify; informational intents never spawn a
    workspace even when the task text looks like a creation request.
    """
    if decision is not None and decision.intent not in _RUN_INTENTS:
        return False
    return should_use_project_workspace(task)


# Task-text markers that ask for a broader (MEDIUM) CVE triage threshold.
_CVE_MEDIUM_HINTS = (
    "medium",
    "med",
    "полный",
    "расширенный",
    "включая medium",
    "начиная с medium",
)


def cve_min_severity_for_task(task: str) -> str:
    """Pick the cve-bin-tool ``--min-severity`` floor for a task: MEDIUM when the
    task explicitly asks for a broader report, otherwise the default HIGH."""
    lowered = task.lower()
    if any(marker in lowered for marker in _CVE_MEDIUM_HINTS):
        return "MEDIUM"
    return "HIGH"


def format_duration(seconds: float) -> str:
    """Format an elapsed duration as ``MM:SS`` (clamped at zero)."""
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    return f"{minutes:02d}:{remainder:02d}"


@contextlib.contextmanager
def temporary_cwd(path: Path):
    """Temporarily ``chdir`` into ``path``, restoring the previous cwd on exit.

    Note: this mutates process-global cwd and is therefore not safe to nest
    across concurrent threads; the GUI serialises its use via the Tk event loop.
    """
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)

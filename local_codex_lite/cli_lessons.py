"""``lessons`` subcommands: inspect and clear the learned pitfalls ledger.

Split out of ``cli.py`` like the other per-command modules; re-exported from
``cli`` so the dispatcher and the test-suite reach the handlers unchanged.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from .cli_utils import console, workspace_root
from .lessons import clear_learned, load_learned
from .run_report import lessons_stats, render_lessons_stats


def cmd_lessons_list(args: argparse.Namespace) -> int:
    root = workspace_root()
    lessons = load_learned(root)
    if not lessons:
        console.print("No learned lessons recorded yet.")
        return 0
    console.print(f"[bold]Learned lessons ({len(lessons)})[/bold]")
    for lesson in lessons:
        when = (
            datetime.fromtimestamp(lesson.ts, tz=UTC).strftime("%Y-%m-%d %H:%M")
            if lesson.ts
            else "n/a"
        )
        # Avoid square brackets around the code: rich would treat them as markup.
        console.print(f"- {lesson.error_code or 'unknown'} | {lesson.signature} ({when})")
        if lesson.task_excerpt:
            console.print(f"    task: {lesson.task_excerpt}")
    return 0


def cmd_lessons_stats(args: argparse.Namespace) -> int:
    """Show per-lesson error recurrence before/after each recorded lesson."""
    root = workspace_root()
    stats = lessons_stats(root)
    # Plain text: signatures may contain square brackets that rich would
    # misinterpret as markup.
    console.print(render_lessons_stats(stats), markup=False)
    return 0


def cmd_lessons_clear(args: argparse.Namespace) -> int:
    root = workspace_root()
    removed = clear_learned(root)
    console.print(f"Cleared {removed} learned lesson(s).")
    return 0

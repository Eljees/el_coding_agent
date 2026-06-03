"""``logs`` subcommands: inspect and compare run directories.

Split out of ``cli.py``; re-exported from ``cli`` so existing callers and the
test-suite (which invoke ``cli.cmd_logs_*``) keep working unchanged.
"""

from __future__ import annotations

import argparse
import json

from .cli_utils import console, workspace_root
from .logging_utils import (
    latest_events_path,
    latest_session_dir,
    resolve_run_dir,
    run_summary,
    tail_events_text,
)


def cmd_logs_latest(args: argparse.Namespace) -> int:
    root = workspace_root()
    run_dir = latest_session_dir(root)
    if run_dir is None:
        console.print("No runs found.")
        return 1
    console.print(f"Latest run: {run_dir}")
    events_path = latest_events_path(root)
    if events_path is None:
        console.print("No events.jsonl found in the latest run.")
        console.print_json(json.dumps(run_summary(run_dir), ensure_ascii=False, indent=2))
        return 0
    console.print(events_path.read_text(encoding="utf-8"))
    return 0


def cmd_logs_tail(args: argparse.Namespace) -> int:
    root = workspace_root()
    run_dir = resolve_run_dir(root, args.run)
    if run_dir is None:
        console.print("No matching run found.")
        return 1
    console.print(f"Run: {run_dir}")
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        console.print(tail_events_text(events_path, lines=args.lines))
        return 0
    console.print("No events.jsonl found; showing run summary instead.")
    console.print_json(json.dumps(run_summary(run_dir), ensure_ascii=False, indent=2))
    return 0


def cmd_logs_show(args: argparse.Namespace) -> int:
    root = workspace_root()
    run_dir = resolve_run_dir(root, args.run_id)
    if run_dir is None:
        console.print("No matching run found.")
        return 1
    summary = run_summary(run_dir)
    console.print(f"Run: {summary['run_dir']}")
    console.print(f"Task: {summary.get('task') or 'n/a'}")
    console.print(f"Status: {summary.get('status')}")
    console.print(f"Selected files: {summary.get('selected_files_count', 0)}")
    console.print(f"Patch: {summary.get('patch_path') or 'n/a'}")
    console.print(f"Evidence: {summary.get('evidence_path') or 'n/a'}")
    if summary.get("patch_error_code"):
        console.print(f"Patch error: {summary['patch_error_code']}")
    evidence_status = summary.get("evidence_status") or {}
    if evidence_status:
        console.print(
            f"Evidence status: {evidence_status.get('status')} / {evidence_status.get('error_code') or 'ok'}"
        )
    artifacts = summary.get("artifacts") or []
    if artifacts:
        console.print("Artifacts:")
        for artifact in artifacts:
            console.print(f"- {artifact}")
    return 0


def cmd_logs_diff(args: argparse.Namespace) -> int:
    """Print a side-by-side comparison of two run directories."""
    root = workspace_root()
    left_dir = resolve_run_dir(root, args.left)
    right_dir = resolve_run_dir(root, args.right)
    if left_dir is None:
        console.print(f"[red]Left run not found:[/red] {args.left}")
        return 1
    if right_dir is None:
        console.print(f"[red]Right run not found:[/red] {args.right}")
        return 1

    left = run_summary(left_dir)
    right = run_summary(right_dir)

    console.print(f"[bold]Left :[/bold] {left['run_dir']}")
    console.print(f"[bold]Right:[/bold] {right['run_dir']}")
    console.print("")

    rows: list[tuple[str, str, str]] = []

    def add(label: str, lkey: str, rkey: str | None = None) -> None:
        rkey = rkey or lkey
        rows.append((label, str(left.get(lkey) or ""), str(right.get(rkey) or "")))

    add("status", "status")
    add("task", "task")
    add("plan summary", "plan_summary")
    add("selected files", "selected_files_count")
    add("patch error", "patch_error_code")

    left_es = left.get("evidence_status") or {}
    right_es = right.get("evidence_status") or {}
    rows.append(
        (
            "evidence",
            f"{left_es.get('status')}/{left_es.get('error_code') or 'ok'}",
            f"{right_es.get('status')}/{right_es.get('error_code') or 'ok'}",
        )
    )

    left_artifacts = set(left.get("artifacts") or [])
    right_artifacts = set(right.get("artifacts") or [])
    only_left = sorted(left_artifacts - right_artifacts)
    only_right = sorted(right_artifacts - left_artifacts)
    rows.append(("artifacts only left", "\n".join(only_left) or "-", ""))
    rows.append(("artifacts only right", "", "\n".join(only_right) or "-"))

    for label, lval, rval in rows:
        console.print(f"[bold]{label}[/bold]")
        console.print(f"  L: {lval if lval else '-'}")
        console.print(f"  R: {rval if rval else '-'}")
    return 0

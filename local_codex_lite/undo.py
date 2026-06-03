"""Restore workspace files from a run's backups/ directory.

When ``runner.run_task`` applies a patch it first copies the affected
files into ``<run_dir>/backups/<relpath>``.  This module turns that
backup directory into a one-step undo: pick a run (latest by default),
walk the backups/, and copy each backup file back over its workspace
counterpart.

Anything outside the workspace root, anything matching a sensitive
filename (.env / *.key / *secret*), or anything that would write to a
path outside the workspace, is skipped with an explanatory line.

The command is read-only by default; pass ``--apply`` to actually
overwrite the workspace.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

from .cli_utils import console, workspace_root
from .logging_utils import resolve_run_dir
from .safety import is_inside_workspace, is_sensitive_path


@dataclass(frozen=True)
class UndoEntry:
    backup_path: Path  # source inside <run_dir>/backups/
    workspace_path: Path  # destination inside the workspace
    skip_reason: str | None  # None when the entry is restorable


def collect_undo_entries(run_dir: Path, workspace_root_path: Path) -> list[UndoEntry]:
    """Walk <run_dir>/backups/ and decide what each entry would do.

    Pure: does not touch the workspace.  Use this both for the dry-run
    listing and for the actual apply.
    """
    backups_dir = run_dir / "backups"
    if not backups_dir.is_dir():
        return []
    entries: list[UndoEntry] = []
    for backup_path in sorted(backups_dir.rglob("*")):
        if not backup_path.is_file():
            continue
        rel = backup_path.relative_to(backups_dir)
        target = (workspace_root_path / rel).resolve()
        reason: str | None = None
        if not is_inside_workspace(target, workspace_root_path):
            reason = "destination outside workspace"
        elif is_sensitive_path(target):
            reason = "destination is a sensitive path"
        entries.append(
            UndoEntry(backup_path=backup_path, workspace_path=target, skip_reason=reason)
        )
    return entries


def cmd_undo(args: argparse.Namespace) -> int:
    root = workspace_root()
    run_ref = getattr(args, "run", None) or "latest"
    run_dir = resolve_run_dir(root, run_ref)
    if run_dir is None:
        console.print(f"[red]No matching run found:[/red] {run_ref}")
        return 1
    entries = collect_undo_entries(run_dir, root)
    if not entries:
        console.print(f"No backups under {run_dir / 'backups'}.")
        return 1

    apply_flag = bool(getattr(args, "apply", False))
    restored = 0
    skipped = 0
    for entry in entries:
        rel = (
            entry.workspace_path.relative_to(root)
            if is_inside_workspace(entry.workspace_path, root)
            else entry.workspace_path
        )
        if entry.skip_reason:
            console.print(f"[yellow]skip[/yellow] {rel}: {entry.skip_reason}")
            skipped += 1
            continue
        if not apply_flag:
            console.print(f"would restore {rel}")
            continue
        entry.workspace_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.backup_path, entry.workspace_path)
        console.print(f"[green]restored[/green] {rel}")
        restored += 1

    console.print("")
    if apply_flag:
        console.print(f"Restored {restored} file(s), skipped {skipped}.")
    else:
        console.print(
            f"Dry run: {len(entries) - skipped} file(s) would be restored, {skipped} skipped."
        )
        console.print("Pass --apply to actually overwrite the workspace.")
    return 0

"""Lifecycle utilities for .local-codex-lite/runs/.

Every CLI invocation that goes through ``runner.run_task`` (and the
evidence sub-commands) creates a new directory under
``<workspace>/.local-codex-lite/runs/<run_id>/``.  Over time that
directory fills up with patches, events.jsonl, evidence bundles,
copies of the workspace files that were touched, etc.  This module
provides two related admin commands:

- ``runs archive``: walk runs/ for entries older than N days and zip
  each one into ``<run_id>.zip`` next to the original directory.  The
  original is left in place unless ``--remove`` is passed.
- ``runs prune``: shorthand for ``runs archive --remove`` -- archive
  and then delete the original directory.

Both default to dry-run; pass ``--apply`` to actually touch anything.
"""
from __future__ import annotations

import argparse
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .cli_utils import console, workspace_root
from .logging_utils import resolve_run_dir


@dataclass(frozen=True)
class RunEntry:
    path: Path
    mtime: datetime
    age_days: float


def _runs_root(workspace: Path) -> Path:
    return workspace / ".local-codex-lite" / "runs"


def list_run_entries(workspace: Path) -> list[RunEntry]:
    """Return every direct subdir of <workspace>/.local-codex-lite/runs/ as
    a RunEntry tagged with its mtime and age in days (UTC, fractional)."""
    runs_root = _runs_root(workspace)
    if not runs_root.is_dir():
        return []
    now = datetime.now(timezone.utc)
    entries: list[RunEntry] = []
    for path in sorted(runs_root.iterdir()):
        if not path.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        age = (now - mtime).total_seconds() / 86400.0
        entries.append(RunEntry(path=path, mtime=mtime, age_days=age))
    return entries


def select_for_archival(entries: list[RunEntry], older_than_days: float) -> list[RunEntry]:
    return [entry for entry in entries if entry.age_days >= older_than_days]


def archive_run(run_dir: Path) -> Path:
    """Zip ``run_dir`` into ``<run_dir>.zip`` next to it.  Returns the
    archive path.  Overwrites an existing archive."""
    archive_path = run_dir.with_suffix(run_dir.suffix + ".zip") if run_dir.suffix else run_dir.parent / f"{run_dir.name}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in run_dir.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(run_dir.parent))
    return archive_path


def cmd_runs_archive(args: argparse.Namespace) -> int:
    workspace = workspace_root()
    older_than = float(getattr(args, "older_than", 30))
    apply_flag = bool(getattr(args, "apply", False))
    remove_flag = bool(getattr(args, "remove", False))

    entries = list_run_entries(workspace)
    if not entries:
        console.print(f"No run directories under {_runs_root(workspace)}.")
        return 1
    selected = select_for_archival(entries, older_than)
    if not selected:
        console.print(
            f"{len(entries)} run(s) found, none older than {older_than:g} day(s).",
        )
        return 0

    console.print(
        f"[bold]{len(selected)}[/bold] of {len(entries)} run(s) are older than "
        f"{older_than:g} day(s).",
    )
    archived = 0
    removed = 0
    for entry in selected:
        rel = entry.path.relative_to(workspace) if entry.path.is_relative_to(workspace) else entry.path
        if not apply_flag:
            action = "would archive + remove" if remove_flag else "would archive"
            console.print(
                f"  {action} {rel} (mtime={entry.mtime.isoformat()}, "
                f"age={entry.age_days:.1f}d)",
            )
            continue
        archive_path = archive_run(entry.path)
        archived += 1
        console.print(f"[green]archived[/green] {rel} -> {archive_path.name}")
        if remove_flag:
            shutil.rmtree(entry.path)
            removed += 1
            console.print(f"[yellow]removed[/yellow] {rel}")

    console.print("")
    if apply_flag:
        console.print(f"Archived {archived} run(s); removed {removed}.")
    else:
        console.print(
            f"Dry run: {len(selected)} run(s) would be touched.  "
            "Pass --apply to actually archive."
        )
    return 0


def cmd_runs_prune(args: argparse.Namespace) -> int:
    """``runs prune`` is ``runs archive --remove`` for ergonomics."""
    args = argparse.Namespace(
        older_than=getattr(args, "older_than", 30),
        apply=getattr(args, "apply", False),
        remove=True,
    )
    return cmd_runs_archive(args)


def cmd_runs_export(args: argparse.Namespace) -> int:
    """Export a single run directory as a self-contained zip.

    Unlike ``runs archive`` this is age-agnostic and on-demand; intended
    for bug reports.  Writes ``<run_id>.zip`` next to the run unless
    ``--out`` is given.
    """
    workspace = workspace_root()
    run_ref = getattr(args, "run", None) or "latest"
    run_dir = resolve_run_dir(workspace, run_ref)
    if run_dir is None:
        console.print(f"[red]No matching run:[/red] {run_ref}")
        return 1
    out_arg = getattr(args, "out", None)
    if out_arg:
        out_path = Path(out_arg)
        if out_path.is_dir():
            out_path = out_path / f"{run_dir.name}.zip"
    else:
        out_path = run_dir.parent / f"{run_dir.name}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in run_dir.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(run_dir.parent))
    console.print(f"[green]exported[/green] {run_dir.name} -> {out_path}")
    return 0

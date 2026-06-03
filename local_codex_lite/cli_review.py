"""Helpers for the ``review`` command: diff acquisition + context building.

Split out of ``cli.py``.  ``cmd_review`` (still in ``cli.py``) drives these;
they are also re-exported from ``cli`` for backwards compatibility.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from subprocess import run as subprocess_run
from typing import Any

from .cli_utils import console, workspace_root
from .config import UnknownProfileError, apply_profile, load_config
from .evidence import save_evidence
from .evidence_mode import (
    create_evidence_bundle,
    save_raw_text,
    save_summary_json,
    save_summary_text,
    write_status,
)
from .logging_utils import dump_json, dump_text, session_dir
from .planner import make_review
from .workspace import read_file_chunks


def _load_review_diff(root: Path, args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "diff_file", []):
        parts: list[str] = []
        for item in args.diff_file:
            path = Path(item)
            if not path.is_absolute():
                path = root / path
            if path.exists():
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return ("\n\n".join(parts), "diff-file")
    if getattr(args, "diff_stdin", False):
        return (sys.stdin.read(), "stdin")
    base = (getattr(args, "base", "") or "").strip()
    head = (getattr(args, "head", "") or "HEAD").strip() or "HEAD"
    if base:
        diff = _git_diff(root, ["diff", "--no-ext-diff", "--unified=3", f"{base}...{head}"])
        return (diff, f"{base}...{head}")
    if getattr(args, "staged", False):
        diff = _git_diff(root, ["diff", "--cached", "--no-ext-diff", "--unified=3"])
        return (diff, "staged")
    diff = _git_diff(root, ["diff", "--no-ext-diff", "--unified=3"])
    return (diff, "working tree")


def _git_diff(root: Path, git_args: list[str]) -> str:
    completed: CompletedProcess[str] = subprocess_run(
        ["git", *git_args], cwd=root, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git diff failed")
    return completed.stdout


def _extract_review_paths(diff_text: str) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        if not (line.startswith("+++ b/") or line.startswith("--- a/")):
            continue
        raw = line[6:].strip()
        if raw == "/dev/null":
            continue
        normalized = raw.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(Path(normalized))
    return paths


def _build_review_context(
    root: Path, diff_text: str, paths: list[Path], selected_files: list[Any]
) -> str:
    top_level = []
    try:
        top_level = [
            entry.name for entry in sorted(root.iterdir(), key=lambda item: item.name.lower())[:20]
        ]
    except OSError:
        top_level = []
    parts = ["# Review summary", f"Files touched: {len(paths)}"]
    if top_level:
        parts.extend(["", "# Top-level entries", *top_level])
    if selected_files:
        parts.append("")
        parts.append("# Current file excerpts")
        for item in selected_files:
            parts.append(f"## {item.path.relative_to(root).as_posix()}")
            parts.append(item.content[:2000])
            parts.append("")
    parts.extend(["", "# Diff", diff_text])
    return "\n".join(parts).strip()


def cmd_review(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    try:
        cfg = apply_profile(cfg, getattr(args, "profile", None))
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    run_dir = session_dir(root)
    evidence_bundle = create_evidence_bundle(
        run_dir, source="manual", task="code review", run_id=run_dir.name
    )
    task = "Review the current code changes for bugs, regressions, missing tests, and maintainability issues."
    diff_text, diff_label = _load_review_diff(root, args)
    if not diff_text.strip():
        console.print("[red]No diff found to review.[/red]")
        return 1
    dump_text(run_dir / "review.diff", diff_text)
    save_raw_text(evidence_bundle, "review.diff", diff_text)
    save_summary_text(evidence_bundle, "review.diff", f"Reviewed diff source: {diff_label}")
    review_paths = _extract_review_paths(diff_text)
    selected_files = read_file_chunks(
        root, review_paths, cfg.workspace.max_file_bytes, cfg.safety.allow_sensitive_read
    )
    if selected_files:
        selected_payload = [
            {"path": item.path.relative_to(root).as_posix(), "content_excerpt": item.content[:2000]}
            for item in selected_files
        ]
        save_summary_json(evidence_bundle, "review_context.json", selected_payload)
        dump_json(run_dir / "review_context.json", selected_payload)
    context = _build_review_context(root, diff_text, review_paths, selected_files)
    review = make_review(task, diff_text, root, cfg, run_dir=run_dir, extra_context=context)
    dump_json(run_dir / "review.json", review)
    save_evidence(run_dir, "review", review)
    save_summary_json(evidence_bundle, "review.json", review)
    write_status(
        evidence_bundle,
        status="ok",
        error_code=None,
        message="review completed",
        evidence_complete=True,
    )
    console.print("[bold]Code review[/bold]")
    console.print_json(json.dumps(review, ensure_ascii=False, indent=2))
    return 0

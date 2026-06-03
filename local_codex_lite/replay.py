"""Replay a saved run without calling the LLM.

See module docstring for details. The command reads task/plan/patch from
a saved run-dir and re-runs the post-LLM pipeline (validate, backup, git
apply, AST gate) on the current workspace.  No LLM is contacted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cli_utils import (
    console,
    workspace_root,
)
from .cli_utils import (
    log_patch_error as _log_patch_error,
)
from .cli_utils import (
    print_patch_error as _print_patch_error,
)
from .config import UnknownProfileError, apply_profile, load_config
from .evidence_mode import create_evidence_bundle, save_raw_text, save_summary_json, write_status
from .logging_utils import dump_json, dump_text, resolve_run_dir, session_dir
from .patch_errors import (
    classify_patch_apply,
    classify_patch_validation,
    classify_python_syntax_error,
)
from .patcher import (
    apply_patch,
    backup_paths,
    restore_from_run_backups,
    validate_diff,
    validate_python_syntax,
)


def _load_replay_inputs(source_run_dir: Path) -> tuple[str, dict, str] | None:
    task_path = source_run_dir / "task.txt"
    plan_path = source_run_dir / "plan.json"
    patch_path = source_run_dir / "patch.diff"
    if not (task_path.is_file() and plan_path.is_file() and patch_path.is_file()):
        return None
    try:
        task = task_path.read_text(encoding="utf-8")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        patch = patch_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return None
    return task, plan, patch


def _extract_touched_paths(patch: str, workspace_root_path: Path) -> list[Path]:
    touched: list[Path] = []
    seen: set[str] = set()
    for line in patch.splitlines():
        if not (line.startswith("+++ b/") or line.startswith("--- a/")):
            continue
        raw = line[6:].strip()
        if raw == "/dev/null":
            continue
        if raw in seen:
            continue
        seen.add(raw)
        touched.append(workspace_root_path / raw)
    return touched


def cmd_replay(args: argparse.Namespace) -> int:
    base_root = workspace_root()
    run_ref = getattr(args, "run_id", None) or "latest"
    source = resolve_run_dir(base_root, run_ref)
    if source is None:
        console.print(f"[red]No matching run:[/red] {run_ref}")
        return 1
    inputs = _load_replay_inputs(source)
    if inputs is None:
        console.print(
            f"[red]Cannot replay {source.name}:[/red] missing or unreadable "
            f"task.txt / plan.json / patch.diff."
        )
        return 1
    task, plan, patch = inputs

    cfg = load_config(base_root)
    try:
        cfg = apply_profile(cfg, getattr(args, "profile", None))
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    run_dir = session_dir(base_root)
    evidence_bundle = create_evidence_bundle(
        run_dir,
        source="replay",
        task=task,
        run_id=run_dir.name,
    )
    dump_text(run_dir / "task.txt", task)
    dump_text(run_dir / "replay_source.txt", str(source))
    save_raw_text(evidence_bundle, "task.txt", task)
    save_summary_json(evidence_bundle, "plan.json", plan)
    save_summary_json(
        evidence_bundle,
        "replay_source.json",
        {"source_run_dir": str(source), "source_run_id": source.name},
    )

    console.print(f"[bold]Replaying run[/bold] {source.name}")
    console.print(f"  task: {task[:80]}{'...' if len(task) > 80 else ''}")
    console.print(f"  new run-dir: {run_dir}")

    if args.dry_run:
        console.print("[bold]Plan[/bold]")
        console.print_json(json.dumps(plan, ensure_ascii=False, indent=2))
        console.print("[bold]Patch (cached)[/bold]")
        console.print(patch)
        write_status(
            evidence_bundle,
            status="ok",
            error_code=None,
            message="replay dry-run completed",
            evidence_complete=True,
        )
        return 0

    if cfg.safety.require_apply_flag and not args.apply:
        write_status(
            evidence_bundle,
            status="partial",
            error_code=None,
            message="apply flag required",
            evidence_complete=False,
        )
        console.print("Use --apply to actually re-run the saved patch.")
        return 0

    validation = validate_diff(
        patch, base_root, allow_sensitive_read=cfg.safety.allow_sensitive_read
    )
    if not validation.ok:
        classification = classify_patch_validation(validation.errors)
        _print_patch_error(classification, 1)
        _log_patch_error(run_dir, "validation", 1, classification, "\n".join(validation.errors))
        dump_json(
            run_dir / "failure.json",
            {"stage": "validation", "patch_error": classification, "errors": validation.errors},
        )
        write_status(
            evidence_bundle,
            status="failed",
            error_code=classification.code,
            message=classification.detail,
            evidence_complete=False,
            extra={"suggested_action": classification.suggested_action},
        )
        return 1

    dump_text(run_dir / "patch.diff", patch)
    touched = _extract_touched_paths(patch, base_root)
    backup_paths(touched, base_root, run_dir=run_dir)
    apply_result = apply_patch(patch, base_root, run_dir=run_dir)
    result = {
        "replay_source": str(source),
        "apply_returncode": apply_result.returncode,
        "apply_stdout": apply_result.stdout,
        "apply_stderr": apply_result.stderr,
    }

    if apply_result.returncode != 0:
        apply_error = classify_patch_apply(apply_result.stderr or "", apply_result.stdout or "")
        already_present = apply_error.code == "file_already_exists"
        if not (already_present and all(p.exists() for p in touched)):
            result["applied"] = False
            result["patch_error"] = apply_error
            dump_json(run_dir / "result.json", result)
            _print_patch_error(apply_error, 1)
            _log_patch_error(
                run_dir, "apply", 1, apply_error, apply_result.stderr or "apply failed"
            )
            dump_json(
                run_dir / "failure.json",
                {"stage": "apply", "patch_error": apply_error, "stderr": apply_result.stderr},
            )
            write_status(
                evidence_bundle,
                status="failed",
                error_code=apply_error.code,
                message=apply_error.detail,
                evidence_complete=False,
                extra={"suggested_action": apply_error.suggested_action},
            )
            return apply_result.returncode or 1
        console.print("[yellow]Patch target already exists; continuing as applied.[/yellow]")

    syntax_issues = validate_python_syntax(touched)
    if syntax_issues:
        restored = restore_from_run_backups(touched, base_root, run_dir)
        detail = "; ".join(f"{issue.path.name}: {issue.detail}" for issue in syntax_issues)
        syntax_error = classify_python_syntax_error(detail)
        result["applied"] = False
        result["patch_error"] = syntax_error
        dump_json(run_dir / "result.json", result)
        _print_patch_error(syntax_error, 1)
        _log_patch_error(run_dir, "post_apply_syntax", 1, syntax_error, detail)
        dump_json(
            run_dir / "failure.json",
            {
                "stage": "post_apply_syntax",
                "patch_error": syntax_error,
                "detail": detail,
                "restored": restored,
            },
        )
        write_status(
            evidence_bundle,
            status="failed",
            error_code=syntax_error.code,
            message=syntax_error.detail,
            evidence_complete=False,
            extra={"suggested_action": syntax_error.suggested_action, "restored": restored},
        )
        return 1

    result["applied"] = True
    dump_json(run_dir / "result.json", result)
    write_status(
        evidence_bundle,
        status="ok",
        error_code=None,
        message="replay applied",
        evidence_complete=True,
    )
    console.print(f"[green]Replay applied[/green]; new run logs at {run_dir}")
    return 0

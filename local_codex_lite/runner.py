"""End-to-end ``run`` workflow extracted from cli.py.

The function lives here (rather than in ``cli.py``) so the CLI module can focus
on argparse wiring and small command handlers, while the much larger
plan -> patch -> validate -> apply -> commands pipeline is in one place that
is easier to test and reason about.

Public surface:

- ``run_task(task, args)`` -- equivalent to the old ``cli._run_task``.
  Returns an integer exit code that ``cli.main`` propagates.

``cli`` re-exports the function as ``cli._run_task`` so existing call sites
and any external code that imported the underscore name keep working.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys

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
from .patch_errors import classify_patch_apply, classify_patch_validation, classify_python_syntax_error
from .patcher import apply_patch, backup_paths, detect_runtime_fix_context, restore_from_run_backups, validate_diff, validate_python_syntax
from .planner import (
    make_patch,
    make_plan,
    repair_patch_with_error,
    revise_plan_with_assumptions,
    suggest_commands,
)
from .project_workspace import resolve_task_workspace
from .retrying import classify_httpx_exception, strategy_for_issue
from .safety import run_command

from .cli_utils import (
    console,
    load_evidence_block as _load_evidence_block,
    log_patch_error as _log_patch_error,
    normalize_suggested_commands as _normalize_suggested_commands,
    print_patch_error as _print_patch_error,
    print_plan_summary as _print_plan_summary,
    print_selected_files as _print_selected_files,
    selected_files as _selected_files,
    workspace_root,
)


def run_task(task: str, args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json_output", False))
    real_stdout = sys.stdout
    # When --json is on we want stdout to carry only the final JSON document
    # so the agent can be wrapped from scripts.  Route every rich print and
    # other incidental writes to stderr for the duration of run_task.
    redirect = contextlib.redirect_stdout(sys.stderr) if json_mode else contextlib.nullcontext()
    with redirect:
        return _run_task_body(task, args, json_mode=json_mode, real_stdout=real_stdout)


def _run_task_body(
    task: str,
    args: argparse.Namespace,
    *,
    json_mode: bool = False,
    real_stdout=None,
) -> int:
    base_root = workspace_root()
    root = resolve_task_workspace(base_root, task)
    if root != base_root:
        console.print(f"Project workspace: {root}")
    cfg = load_config(root)
    try:
        cfg = apply_profile(cfg, getattr(args, "profile", None))
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    evidence_text = _load_evidence_block(
        getattr(args, "evidence_file", []),
        use_stdin=getattr(args, "evidence_stdin", False),
    )
    runtime_fix = detect_runtime_fix_context(task, evidence_text, root)
    run_dir = session_dir(root)
    evidence_bundle = create_evidence_bundle(run_dir, source="manual", task=task, run_id=run_dir.name)
    dump_text(run_dir / "task.txt", task)
    save_raw_text(evidence_bundle, "task.txt", task)
    if evidence_text:
        save_raw_text(evidence_bundle, "user_evidence.txt", evidence_text)
        save_summary_text(
            evidence_bundle,
            "user_evidence.txt",
            "User-provided traceback or logs were attached for repair.",
        )
    selected = _selected_files(root, task, cfg)
    _print_selected_files(root, selected)
    selected_payload = [
        {
            "path": item.path.relative_to(root).as_posix(),
            "score": item.score,
            "reasons": list(item.reasons),
        }
        for item in selected
    ]
    save_summary_json(evidence_bundle, "selected_files.json", selected_payload)
    save_evidence(run_dir, "selected_files", selected_payload)
    console.print("[bold]Planning...[/bold]")
    plan = make_plan(task, root, cfg, run_dir=run_dir, extra_context=evidence_text, runtime_fix=runtime_fix)
    dump_json(run_dir / "plan.json", plan)
    save_evidence(run_dir, "plan", plan)
    save_summary_json(evidence_bundle, "plan.json", plan)
    console.print("[bold]Planning done[/bold]")
    _print_plan_summary(plan)
    dump_text(run_dir / "selected_context.txt", "see plan/prompt context in session")
    result = {"dry_run": bool(args.dry_run), "apply": bool(args.apply), "exec": bool(args.execute)}

    if plan.get("needs_clarification"):
        questions = plan.get("clarifying_questions") if isinstance(plan.get("clarifying_questions"), list) else []
        if questions:
            console.print("[yellow]Plan needs clarification.[/yellow]")
            for question in questions:
                console.print(f"- {question}")
        if args.assume_clarification:
            console.print("[yellow]Assuming reasonable defaults and continuing...[/yellow]")
            plan = revise_plan_with_assumptions(task, plan, root, cfg, run_dir=run_dir, extra_context=evidence_text)
            dump_json(run_dir / "plan.json", plan)
            save_summary_json(evidence_bundle, "plan.json", plan)
            console.print("[bold]Revised plan[/bold]")
            console.print_json(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            dump_json(run_dir / "result.json", result)
            write_status(evidence_bundle, status="partial", error_code=None, message="awaiting clarification", evidence_complete=False)
            console.print("Use --assume-clarification to continue with reasonable defaults.")
            return 0

    console.print("[bold]Plan[/bold]")
    console.print_json(json.dumps(plan, ensure_ascii=False, indent=2))

    if args.dry_run:
        console.print("[dim]Dry-run mode: skipping patch and commands[/dim]")
        dump_json(run_dir / "result.json", result)
        write_status(evidence_bundle, status="ok", error_code=None, message="dry-run completed", evidence_complete=True)
        if json_mode:
            payload = {
                "task": task,
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                "selected_files": selected_payload,
                "plan": plan,
                "result": result,
            }
            target = real_stdout if real_stdout is not None else sys.__stdout__
            target.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            target.flush()
        return 0

    if cfg.safety.require_apply_flag and not args.apply:
        result["applied"] = False
        dump_json(run_dir / "result.json", result)
        write_status(evidence_bundle, status="partial", error_code=None, message="apply flag required", evidence_complete=False)
        console.print("Use --apply to write changes.")
        return 0

    console.print("[bold]Generating patch...[/bold]")
    try:
        patch = make_patch(task, plan, root, cfg, run_dir=run_dir, extra_context=evidence_text, runtime_fix=runtime_fix)
    except Exception as exc:  # noqa: BLE001
        issue = classify_httpx_exception(exc)
        failure = {"stage": "patch", "issue_type": issue, "strategy": strategy_for_issue(issue), "error": str(exc)}
        result["failure"] = failure
        dump_json(run_dir / "result.json", result)
        dump_json(run_dir / "failure.json", failure)
        write_status(evidence_bundle, status="failed", error_code="patch_generation_failed", message=str(exc), evidence_complete=False)
        console.print("[red]Patch generation failed[/red]")
        console.print_json(json.dumps(failure, ensure_ascii=False, indent=2))
        console.print(f"Run logs: {run_dir}")
        return 1

    patch_attempts = 0
    # Allow a CLI-level override so --max-patch-attempts wins over the config
    # default for a single run; getattr keeps the call signature back-
    # compatible with older Namespaces that don't carry the field.
    override = getattr(args, "max_patch_attempts", None)
    max_patch_attempts = int(override) if override else cfg.safety.max_patch_attempts
    while True:
        patch_attempts += 1
        dump_text(run_dir / "patch.diff", patch)
        validation = validate_diff(patch, root, allow_sensitive_read=cfg.safety.allow_sensitive_read)
        result["diff_valid"] = validation.ok
        result["validation_errors"] = validation.errors
        if not validation.ok:
            classification = classify_patch_validation(validation.errors)
            _print_patch_error(classification, patch_attempts)
            _log_patch_error(run_dir, "validation", patch_attempts, classification, "\n".join(validation.errors))
            if not classification.retryable:
                result["patch_error"] = classification
                dump_json(run_dir / "result.json", result)
                dump_json(run_dir / "failure.json", {"stage": "validation", "patch_error": classification})
                write_status(evidence_bundle, status="failed", error_code=classification.code, message=classification.detail, evidence_complete=False, extra={"suggested_action": classification.suggested_action})
                console.print(f"Run logs: {run_dir}")
                return 1
            if patch_attempts < max_patch_attempts:
                console.print("[yellow]Patch validation failed; repairing diff and retrying...[/yellow]")
                for error in validation.errors:
                    console.print(f"- {error}")
                patch = repair_patch_with_error(task, plan, patch, "\n".join(validation.errors), classification.code, root, cfg, extra_context=evidence_text, repair_attempt=patch_attempts, runtime_fix=runtime_fix)
                dump_json(run_dir / "validation_issue.json", {"patch_error": classification, "errors": validation.errors})
                continue
            dump_json(run_dir / "result.json", result)
            dump_json(run_dir / "failure.json", {"stage": "validation", "patch_error": classification, "errors": validation.errors})
            write_status(evidence_bundle, status="failed", error_code=classification.code, message=classification.detail, evidence_complete=False, extra={"suggested_action": classification.suggested_action})
            console.print("[red]Patch validation failed[/red]")
            for error in validation.errors:
                console.print(f"- {error}")
            console.print(f"Run logs: {run_dir}")
            return 1

        console.print("\n[bold]Patch preview[/bold]")
        console.print(patch)
        touched = []
        for line in patch.splitlines():
            if line.startswith("+++ b/") or line.startswith("--- a/"):
                raw = line[6:].strip()
                if raw != "/dev/null":
                    touched.append(root / raw)
        backup_paths(touched, root, run_dir=run_dir)
        apply_result = apply_patch(patch, root, run_dir=run_dir)
        result["apply_returncode"] = apply_result.returncode
        result["apply_stdout"] = apply_result.stdout
        result["apply_stderr"] = apply_result.stderr
        result["patch_attempts"] = patch_attempts
        apply_error = classify_patch_apply(apply_result.stderr or "", apply_result.stdout or "")
        already_present = apply_error.code == "file_already_exists"
        if apply_result.returncode == 0 or (already_present and all(path.exists() for path in touched)):
            if already_present and apply_result.returncode != 0:
                console.print("[yellow]Patch target already exists; continuing as applied.[/yellow]")
            # Post-apply AST gate: if any touched .py file no longer parses,
            # the model gave us a syntactically broken patch. Restore the
            # backups and run the repair loop instead of declaring success.
            syntax_issues = validate_python_syntax(touched)
            if syntax_issues:
                restored = restore_from_run_backups(touched, root, run_dir)
                detail = "; ".join(f"{issue.path.name}: {issue.detail}" for issue in syntax_issues)
                console.print(
                    f"[red]Python syntax error after apply[/red] in {len(syntax_issues)} file(s); "
                    f"restored {restored} from backups."
                )
                syntax_error = classify_python_syntax_error(detail)
                result["applied"] = False
                result["patch_error"] = syntax_error
                dump_json(run_dir / "result.json", result)
                _print_patch_error(syntax_error, patch_attempts)
                _log_patch_error(run_dir, "post_apply_syntax", patch_attempts, syntax_error, detail)
                if patch_attempts < max_patch_attempts:
                    console.print("[yellow]Repairing patch and retrying after syntax error...[/yellow]")
                    patch = repair_patch_with_error(
                        task, plan, patch, detail, syntax_error.code, root, cfg,
                        extra_context=evidence_text, repair_attempt=patch_attempts,
                        runtime_fix=runtime_fix,
                    )
                    dump_json(run_dir / "apply_issue.json", {"patch_error": syntax_error, "detail": detail})
                    continue
                dump_json(
                    run_dir / "failure.json",
                    {"stage": "post_apply_syntax", "patch_error": syntax_error, "detail": detail},
                )
                write_status(
                    evidence_bundle, status="failed", error_code=syntax_error.code,
                    message=syntax_error.detail, evidence_complete=False,
                    extra={"suggested_action": syntax_error.suggested_action},
                )
                console.print(f"Run logs: {run_dir}")
                return 1
            result["apply_returncode"] = 0
            result["applied"] = True
            result["patch_error"] = apply_error
            dump_json(run_dir / "result.json", result)
            write_status(evidence_bundle, status="ok", error_code=apply_error.code, message="patch applied", evidence_complete=True, extra={"suggested_action": apply_error.suggested_action})
            break
        result["applied"] = False
        result["patch_error"] = apply_error
        dump_json(run_dir / "result.json", result)
        _print_patch_error(apply_error, patch_attempts)
        _log_patch_error(run_dir, "apply", patch_attempts, apply_error, apply_result.stderr or apply_result.stdout or "apply failed")
        if not apply_error.retryable:
            dump_json(run_dir / "failure.json", {"stage": "apply", "patch_error": apply_error, "stderr": apply_result.stderr})
            write_status(evidence_bundle, status="failed", error_code=apply_error.code, message=apply_error.detail, evidence_complete=False, extra={"suggested_action": apply_error.suggested_action})
            console.print(f"Run logs: {run_dir}")
            return apply_result.returncode or 1
        if patch_attempts < max_patch_attempts:
            console.print("[yellow]Patch apply failed; repairing diff and retrying...[/yellow]")
            if apply_result.stderr:
                console.print(apply_result.stderr)
            patch = repair_patch_with_error(task, plan, patch, apply_result.stderr or apply_result.stdout or "apply failed", apply_error.code, root, cfg, extra_context=evidence_text, repair_attempt=patch_attempts, runtime_fix=runtime_fix)
            dump_json(run_dir / "apply_issue.json", {"patch_error": apply_error, "stderr": apply_result.stderr})
            continue
        if apply_result.stderr:
            console.print(apply_result.stderr)
        dump_json(run_dir / "failure.json", {"stage": "apply", "patch_error": apply_error, "stderr": apply_result.stderr})
        write_status(evidence_bundle, status="failed", error_code=apply_error.code, message=apply_error.detail, evidence_complete=False, extra={"suggested_action": apply_error.suggested_action})
        console.print(f"Run logs: {run_dir}")
        return apply_result.returncode

    console.print("[bold]Suggesting commands...[/bold]")
    commands = suggest_commands(task, plan, root, cfg, run_dir=run_dir, extra_context=evidence_text, runtime_fix=runtime_fix)
    commands = _normalize_suggested_commands(commands)
    dump_json(run_dir / "commands.json", commands)
    console.print("\n[bold]Commands[/bold]")
    console.print_json(json.dumps(commands, ensure_ascii=False, indent=2))

    if args.execute and commands.get("commands"):
        exec_outputs = []
        for item in commands["commands"]:
            cmd = item["cmd"]
            try:
                completed = run_command(cmd, cwd=root, timeout=120)
                exec_outputs.append({"cmd": cmd, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
            except ValueError as exc:
                exec_outputs.append({"cmd": cmd, "returncode": 126, "stdout": "", "stderr": str(exc)})
        dump_json(run_dir / "test_outputs.json", exec_outputs)
    write_status(evidence_bundle, status="ok", error_code=None, message="run completed", evidence_complete=True)
    return 0

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import AgentConfig, config_as_dict, config_path, default_config, load_config, save_config
from .doctor import preview_patch, run_dependency_doctor, run_doctor, run_rag_doctor
from .evidence_mode import create_evidence_bundle, save_raw_text, save_summary_json, save_summary_text, write_status
from .logging_utils import (
    append_jsonl,
    dump_json,
    dump_text,
    latest_events_path,
    latest_session_dir,
    resolve_run_dir,
    run_summary,
    session_dir,
    tail_events_text,
)
from .patch_errors import PatchErrorClassification, classify_patch_apply, classify_patch_validation
from .patcher import apply_patch, backup_paths, validate_diff
from .planner import make_patch, make_plan, repair_patch_with_error, revise_plan_with_assumptions, suggest_commands
from .project_workspace import resolve_task_workspace
from .prompts import ask_prompt, evidence_question_prompt
from .retrying import classify_httpx_exception, strategy_for_issue
from .rich_compat import make_console
from .capabilities import default_capabilities
from .safety import run_command
from .intent import decision_as_dict, recognize_intent
from .llm_client import OpenAICompatibleClient
from .rag import (
    RagProviderError,
    ensure_rag_provider_supported,
    format_retrieved_context,
    index_workspace as rag_index_workspace,
    query_index as rag_query_index,
    retrieve_rag_context,
)
from .patcher import detect_runtime_fix_context
from .ui import run_command_center_ui
from .workspace import RankedWorkspaceFile, summarize_ranked_files
from .evidence import save_evidence

# ── helpers from split modules (re-exported for backward compatibility) ───────
from .cli_utils import (  # noqa: F401
    workspace_root,
    ensure_utf8_output as _ensure_utf8_output,
    print_selected_files as _print_selected_files,
    print_plan_summary as _print_plan_summary,
    print_patch_error as _print_patch_error,
    log_patch_error as _log_patch_error,
    sanitize_log_text as _sanitize_log_text,
    selected_files as _selected_files,
    load_urls as _load_urls,
    normalize_suggested_commands as _normalize_suggested_commands,
    looks_like_shell_command as _looks_like_shell_command,
    load_evidence_block as _load_evidence_block,
    load_rag_context as _load_rag_context,
    print_retrieved_rag_context as _print_retrieved_rag_context,
    merge_context_blocks as _merge_context_blocks,
    render_evidence_item as _render_evidence_item,
    read_stdin_evidence as _read_stdin_evidence,
    console,
)
from .cli_evidence import (  # noqa: F401
    cmd_evidence_json_compare,
    cmd_evidence_artifacts_inspect,
    cmd_evidence_trufflehog_scan,
    cmd_evidence_trufflehog_analyze,
    cmd_evidence_trufflehog_compare,
    cmd_evidence_cve_scan,
)


def cmd_init(args: argparse.Namespace) -> int:
    root = workspace_root()
    path = config_path(root)
    if path.exists():
        console.print(f"Config already exists: {path}")
        return 0
    save_config(root, default_config())
    console.print(f"Created {path}")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    cfg = load_config(workspace_root())
    console.print_json(json.dumps(config_as_dict(cfg), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    console.print(f"Workspace: {root}")
    console.print(f"Config: {config_path(root)}")
    console.print(f"LLM: {cfg.llm.base_url} / {cfg.llm.model}")
    return 0


def cmd_recognize(args: argparse.Namespace) -> int:
    decision = recognize_intent(args.task, default_capabilities())
    console.print_json(json.dumps(decision_as_dict(decision), ensure_ascii=False, indent=2))
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    return run_command_center_ui(autoclose_ms=getattr(args, "autoclose_ms", None))


def cmd_preview(args: argparse.Namespace) -> int:
    base_root = workspace_root()
    root = resolve_task_workspace(base_root, args.task)
    if root != base_root:
        console.print(f"Project workspace: {root}")
    cfg = load_config(root)
    evidence_text = _load_evidence_block(args.evidence_file, use_stdin=args.evidence_stdin)
    runtime_fix = detect_runtime_fix_context(args.task, evidence_text, root)
    rag_context_text = _load_rag_context(root, cfg, args.task) if getattr(args, "rag", False) else ""
    selected = _selected_files(root, args.task, cfg)
    _print_selected_files(root, selected)
    if rag_context_text:
        _print_retrieved_rag_context(rag_context_text)
    try:
        plan = make_plan(
            args.task,
            root,
            cfg,
            extra_context=_merge_context_blocks(evidence_text, rag_context_text),
            runtime_fix=runtime_fix,
        )
        _print_plan_summary(plan)
        patch = make_patch(
            args.task,
            plan,
            root,
            cfg,
            extra_context=_merge_context_blocks(evidence_text, rag_context_text),
            runtime_fix=runtime_fix,
        )
        return preview_patch(root, patch)
    except RagProviderError as exc:
        console.print("[red]RAG unavailable[/red]")
        console.print(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        console.print("[red]Preview failed[/red]")
        console.print(f"{exc.__class__.__name__}: {exc}")
        return 1


def _run_task(task: str, args: argparse.Namespace) -> int:
    base_root = workspace_root()
    root = resolve_task_workspace(base_root, task)
    if root != base_root:
        console.print(f"Project workspace: {root}")
    cfg = load_config(root)
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
    result = {"dry_run": bool(args.dry_run), "apply": bool(args.apply), "exec": bool(args.exec)}

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
    max_patch_attempts = cfg.safety.max_patch_attempts
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
        backup_paths(touched, root)
        apply_result = apply_patch(patch, root)
        result["apply_returncode"] = apply_result.returncode
        result["apply_stdout"] = apply_result.stdout
        result["apply_stderr"] = apply_result.stderr
        result["patch_attempts"] = patch_attempts
        apply_error = classify_patch_apply(apply_result.stderr or "", apply_result.stdout or "")
        already_present = apply_error.code == "file_already_exists"
        if apply_result.returncode == 0 or (already_present and all(path.exists() for path in touched)):
            if already_present and apply_result.returncode != 0:
                console.print("[yellow]Patch target already exists; continuing as applied.[/yellow]")
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

    if args.exec and commands.get("commands"):
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


def cmd_ask(question: str, args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    context = f"Workspace root: {root}\nConfig path: {config_path(root)}"
    evidence_text = _load_evidence_block(args.evidence_file, use_stdin=args.evidence_stdin)
    try:
        rag_context_text = _load_rag_context(root, cfg, question) if getattr(args, "rag", False) else ""
        client = OpenAICompatibleClient(cfg.llm)
        if rag_context_text:
            _print_retrieved_rag_context(rag_context_text)
        messages = ask_prompt(question, context, evidence=evidence_text, rag_context=rag_context_text)
        response = client.chat(messages, status_label="Answering question")
        console.print(response.text)
        return 0
    except RagProviderError as exc:
        console.print("[red]RAG unavailable[/red]")
        console.print(str(exc))
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    return run_doctor(workspace_root())


def cmd_doctor_deps(args: argparse.Namespace) -> int:
    return run_dependency_doctor(workspace_root())


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
        console.print(f"Evidence status: {evidence_status.get('status')} / {evidence_status.get('error_code') or 'ok'}")
    artifacts = summary.get("artifacts") or []
    if artifacts:
        console.print("Artifacts:")
        for artifact in artifacts:
            console.print(f"- {artifact}")
    return 0


def cmd_rag_index(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    try:
        info = rag_index_workspace(root, cfg)
    except RagProviderError as exc:
        console.print("[red]RAG index failed[/red]")
        console.print(str(exc))
        return 1
    console.print(f"RAG index built: {info.index_path}")
    console.print(f"Provider: {info.provider}")
    console.print(f"Chunks: {info.chunk_count}")
    console.print(f"Files: {info.file_count}")
    return 0


def cmd_rag_query(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    try:
        retrieved = rag_query_index(args.query, root, cfg, top_k=args.top_k)
    except RagProviderError as exc:
        console.print("[red]RAG query failed[/red]")
        console.print(str(exc))
        return 1
    if not retrieved:
        console.print("No RAG matches found.")
        return 0
    _print_retrieved_rag_context(format_retrieved_context(retrieved, cfg.rag.max_context_chars))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-codex-lite")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("status")
    p_recognize = sub.add_parser("recognize")
    p_recognize.add_argument("task")
    p_ui = sub.add_parser("ui")
    p_ui.add_argument("--autoclose-ms", type=int)
    p_doctor = sub.add_parser("doctor")
    doctor_sub = p_doctor.add_subparsers(dest="doctor_command")
    doctor_sub.required = False
    p_doctor.set_defaults(doctor_command="run")
    doctor_sub.add_parser("deps")
    doctor_sub.add_parser("rag")
    config_parser = sub.add_parser("config")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")

    p_run = sub.add_parser("run")
    p_run.add_argument("task")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--apply", action="store_true")
    p_run.add_argument("--exec", action="store_true")
    p_run.add_argument("--assume-clarification", action="store_true")
    p_run.add_argument("--evidence-file", action="append", default=[])
    p_run.add_argument("--evidence-stdin", action="store_true")

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question")
    p_ask.add_argument("--evidence-file", action="append", default=[])
    p_ask.add_argument("--evidence-stdin", action="store_true")
    p_ask.add_argument("--rag", action="store_true")

    p_preview = sub.add_parser("preview")
    p_preview.add_argument("task")
    p_preview.add_argument("--evidence-file", action="append", default=[])
    p_preview.add_argument("--evidence-stdin", action="store_true")
    p_preview.add_argument("--rag", action="store_true")

    p_rag = sub.add_parser("rag")
    rag_sub = p_rag.add_subparsers(dest="rag_command", required=True)
    p_rag_index = rag_sub.add_parser("index")
    p_rag_index.add_argument("--rebuild", action="store_true")
    p_rag_query = rag_sub.add_parser("query")
    p_rag_query.add_argument("query")
    p_rag_query.add_argument("--top-k", type=int, default=None)

    p_logs = sub.add_parser("logs")
    logs_sub = p_logs.add_subparsers(dest="logs_command", required=True)
    logs_sub.add_parser("latest")
    p_logs_tail = logs_sub.add_parser("tail")
    p_logs_tail.add_argument("--lines", type=int, default=40)
    p_logs_tail.add_argument("--run", default="latest")
    p_logs_show = logs_sub.add_parser("show")
    p_logs_show.add_argument("run_id")

    p_evidence = sub.add_parser("evidence")
    evidence_sub = p_evidence.add_subparsers(dest="evidence_command", required=True)

    p_json = evidence_sub.add_parser("json-compare")
    p_json.add_argument("left")
    p_json.add_argument("right")
    p_json.add_argument("--out")

    p_artifacts = evidence_sub.add_parser("artifacts")
    artifacts_sub = p_artifacts.add_subparsers(dest="artifacts_command", required=True)
    p_artifacts_inspect = artifacts_sub.add_parser("inspect")
    p_artifacts_inspect.add_argument("input_root")
    p_artifacts_inspect.add_argument("extract_to", nargs="?")
    p_artifacts_inspect.add_argument("--extract", action="store_true")
    p_artifacts_inspect.add_argument("--extract-to", dest="extract_to_flag")
    p_artifacts_inspect.add_argument("--max-depth", type=int, default=2)
    p_artifacts_inspect.add_argument("--max-files", type=int, default=2000)
    p_artifacts_inspect.add_argument("--max-total-bytes", type=int, default=500_000_000)

    p_th = evidence_sub.add_parser("trufflehog")
    th_sub = p_th.add_subparsers(dest="trufflehog_command", required=True)
    p_th_scan = th_sub.add_parser("scan")
    p_th_scan.add_argument("--repo-url", action="append")
    p_th_scan.add_argument("--repo-file")
    p_th_scan.add_argument("--git-user", default=os.environ.get("GITLAB_USER", "").strip())
    p_th_scan.add_argument("--git-token", default=os.environ.get("GITLAB_TOKEN", "").strip())
    p_th_scan.add_argument("--image", default=os.environ.get("TRUFFLEHOG_IMAGE", "trufflesecurity/trufflehog:3.94.1"))
    p_th_scan.add_argument("--cache-root", default=os.environ.get("TRUFFLEHOG_CACHE_ROOT", ""))
    p_th_scan.add_argument("--out-root", default=os.environ.get("TRUFFLEHOG_OUT_ROOT", ""))
    p_th_scan.add_argument("--depth", type=int, default=1)
    p_th_scan.add_argument("--keep-clones", action="store_true")

    p_th_analyze = th_sub.add_parser("analyze")
    p_th_analyze.add_argument("input_root")
    p_th_analyze.add_argument("--out")

    p_th_compare = th_sub.add_parser("compare")
    p_th_compare.add_argument("left")
    p_th_compare.add_argument("right")
    p_th_compare.add_argument("--out")

    p_cve = evidence_sub.add_parser("cve-scan", help="CVE scan tool runner")
    p_cve.add_argument("action_or_input", nargs="?", help="status | install | update-db | scan | <input_root>")
    p_cve.add_argument("input_root", nargs="?", help="Path to artifacts directory (may contain archives)")
    p_cve.add_argument("--extract-to", dest="extract_to", default=None)
    p_cve.add_argument("--output-dir", dest="output_dir", default=None)
    p_cve.add_argument("--install", action="store_true", help="Auto-install cve-bin-tool if missing")
    p_cve.add_argument("--update-db", dest="update_db", action="store_true", help="Update CVE database before scan")
    p_cve.add_argument("--skip-unpack", dest="skip_unpack", action="store_true", help="Skip archive extraction")
    p_cve.add_argument("--offline", action="store_true", help="Run cve-bin-tool in offline mode")
    p_cve.add_argument("--min-severity", dest="min_severity", default="HIGH",
                       choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    p_cve.add_argument("--format", default="json,md,high-critical-md")

    return parser


def main() -> int:
    _ensure_utf8_output()
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "init":
        return cmd_init(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "recognize":
        return cmd_recognize(args)
    if args.command == "ui":
        return cmd_ui(args)
    if args.command == "doctor":
        if getattr(args, "doctor_command", "run") == "deps":
            return cmd_doctor_deps(args)
        if getattr(args, "doctor_command", "run") == "rag":
            return run_rag_doctor(workspace_root())
        return cmd_doctor(args)
    if args.command == "config":
        if args.config_command == "show":
            return cmd_config_show(args)
    if args.command == "run":
        return _run_task(args.task, args)
    if args.command == "ask":
        return cmd_ask(args.question, args)
    if args.command == "preview":
        return cmd_preview(args)
    if args.command == "rag":
        if args.rag_command == "index":
            return cmd_rag_index(args)
        if args.rag_command == "query":
            return cmd_rag_query(args)
    if args.command == "logs":
        if args.logs_command == "latest":
            return cmd_logs_latest(args)
        if args.logs_command == "tail":
            return cmd_logs_tail(args)
        if args.logs_command == "show":
            return cmd_logs_show(args)
    if args.command == "evidence":
        if args.evidence_command == "json-compare":
            return cmd_evidence_json_compare(args)
        if args.evidence_command == "artifacts":
            return cmd_evidence_artifacts_inspect(args)
        if args.evidence_command == "trufflehog":
            th_cmd = getattr(args, "trufflehog_command", None)
            if th_cmd == "scan":
                return cmd_evidence_trufflehog_scan(args)
            if th_cmd == "analyze":
                return cmd_evidence_trufflehog_analyze(args)
            if th_cmd == "compare":
                return cmd_evidence_trufflehog_compare(args)
        if args.evidence_command == "cve-scan":
            return cmd_evidence_cve_scan(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

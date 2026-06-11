from __future__ import annotations

import argparse
import sys  # noqa: F401  # re-exported as cli.sys; patched by the stdin-evidence tests

from .cli_evidence import (
    cmd_evidence_artifacts_inspect,
    cmd_evidence_cve_scan,
    cmd_evidence_cve_scan_history,
    cmd_evidence_json_compare,
    cmd_evidence_trufflehog_analyze,
    cmd_evidence_trufflehog_compare,
    cmd_evidence_trufflehog_scan,
)
from .cli_info import (
    cmd_config_show,
    cmd_init,
    cmd_recognize,
    cmd_status,
)
from .cli_lessons import (
    cmd_lessons_clear,
    cmd_lessons_list,
    cmd_lessons_stats,
)
from .cli_logs import (
    cmd_logs_attempts,
    cmd_logs_diff,
    cmd_logs_latest,
    cmd_logs_show,
    cmd_logs_tail,
)
from .cli_parser import build_parser
from .cli_query import cmd_ask, cmd_preview
from .cli_rag import cmd_rag_index, cmd_rag_query
from .cli_review import (
    cmd_review,
)
from .cli_rules import (
    cmd_rules_init,
    cmd_rules_show,
)
from .cli_utils import (
    ensure_utf8_output as _ensure_utf8_output,
)
from .cli_utils import (
    load_evidence_block as _load_evidence_block,
)
from .cli_utils import (
    load_rag_context as _load_rag_context,
)
from .cli_utils import (
    load_urls as _load_urls,
)
from .cli_utils import (
    log_patch_error as _log_patch_error,
)
from .cli_utils import (
    looks_like_shell_command as _looks_like_shell_command,
)
from .cli_utils import (
    merge_context_blocks as _merge_context_blocks,
)
from .cli_utils import (
    normalize_suggested_commands as _normalize_suggested_commands,
)
from .cli_utils import (
    print_patch_error as _print_patch_error,
)
from .cli_utils import (
    print_plan_summary as _print_plan_summary,
)
from .cli_utils import (
    print_retrieved_rag_context as _print_retrieved_rag_context,
)
from .cli_utils import (
    print_selected_files as _print_selected_files,
)
from .cli_utils import (
    read_stdin_evidence as _read_stdin_evidence,
)
from .cli_utils import (
    render_evidence_item as _render_evidence_item,
)
from .cli_utils import (
    sanitize_log_text as _sanitize_log_text,
)
from .cli_utils import (
    selected_files as _selected_files,
)

# ── helpers from split modules (re-exported for backward compatibility) ───────
from .cli_utils import (
    workspace_root,
)
from .config import (
    default_config,
)
from .doctor import (
    run_dependency_doctor,
    run_doctor,
    run_full_doctor,
    run_rag_doctor,
)
from .plugins_cmd import cmd_plugins_list
from .replay import cmd_replay
from .runs_admin import (
    cmd_projects_cleanup,
    cmd_runs_archive,
    cmd_runs_cleanup,
    cmd_runs_export,
    cmd_runs_prune,
)
from .ui import run_command_center_ui
from .undo import cmd_undo


def cmd_ui(args: argparse.Namespace) -> int:
    return run_command_center_ui(autoclose_ms=getattr(args, "autoclose_ms", None))


def cmd_doctor(args: argparse.Namespace) -> int:
    return run_doctor(workspace_root())


def cmd_doctor_deps(args: argparse.Namespace) -> int:
    return run_dependency_doctor(workspace_root())


# _run_task moved to local_codex_lite.runner.run_task in stage 3b.
# We re-export it under the old underscore name so cli.main() and any
# external code that imports cli._run_task keep working without change.
from .runner import run_task as _run_task  # noqa: E402

# Names re-exported for external/test callers; keep in __all__ so the
# ruff F401/isort autofix never strips them.
__all__ = [
    "_ensure_utf8_output",
    "_load_evidence_block",
    "_load_rag_context",
    "_load_urls",
    "_log_patch_error",
    "_looks_like_shell_command",
    "_merge_context_blocks",
    "_normalize_suggested_commands",
    "_print_patch_error",
    "_print_plan_summary",
    "_print_retrieved_rag_context",
    "_print_selected_files",
    "_read_stdin_evidence",
    "_render_evidence_item",
    "_run_task",
    "_sanitize_log_text",
    "_selected_files",
    "build_parser",
    "cmd_ask",
    "cmd_config_show",
    "cmd_init",
    "cmd_lessons_clear",
    "cmd_lessons_list",
    "cmd_lessons_stats",
    "cmd_logs_attempts",
    "cmd_logs_diff",
    "cmd_logs_latest",
    "cmd_logs_show",
    "cmd_logs_tail",
    "cmd_preview",
    "cmd_rag_index",
    "cmd_rag_query",
    "cmd_recognize",
    "cmd_review",
    "cmd_rules_init",
    "cmd_rules_show",
    "cmd_status",
    "default_config",
]


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
        if getattr(args, "doctor_command", "run") == "full":
            return run_full_doctor(workspace_root())
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
    if args.command == "review":
        return cmd_review(args)
    if args.command == "runs":
        if args.runs_command == "archive":
            return cmd_runs_archive(args)
        if args.runs_command == "prune":
            return cmd_runs_prune(args)
        if args.runs_command == "export":
            return cmd_runs_export(args)
        if args.runs_command == "cleanup":
            return cmd_runs_cleanup(args)
    if args.command == "projects":
        if args.projects_command == "cleanup":
            return cmd_projects_cleanup(args)
    if args.command == "replay":
        return cmd_replay(args)
    if args.command == "undo":
        return cmd_undo(args)
    if args.command == "plugins":
        if args.plugins_command == "list":
            return cmd_plugins_list(args)
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
        if args.logs_command == "attempts":
            return cmd_logs_attempts(args)
        if args.logs_command == "diff":
            return cmd_logs_diff(args)
    if args.command == "lessons":
        if args.lessons_command == "list":
            return cmd_lessons_list(args)
        if args.lessons_command == "stats":
            return cmd_lessons_stats(args)
        if args.lessons_command == "clear":
            return cmd_lessons_clear(args)
    if args.command == "rules":
        if args.rules_command == "show":
            return cmd_rules_show(args)
        if args.rules_command == "init":
            return cmd_rules_init(args)
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
        if args.evidence_command == "cve-scan-history":
            return cmd_evidence_cve_scan_history(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

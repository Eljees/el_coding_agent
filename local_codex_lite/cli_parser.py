"""argparse wiring for the local-codex-lite CLI.

Split out of ``cli.py`` so the command surface lives in one place and the
dispatcher module stays focused on behaviour.  ``cli.build_parser`` remains
importable (re-exported) for backwards compatibility and the test-suite.
"""

from __future__ import annotations

import argparse
import os


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
    doctor_sub.add_parser("full", help="aggregate core + deps + rag + tool probes")
    config_parser = sub.add_parser("config")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")

    p_run = sub.add_parser("run")
    p_run.add_argument("task")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--apply", action="store_true")
    p_run.add_argument(
        "--exec",
        dest="execute",
        action="store_true",
        help="run suggested commands after a successful apply",
    )
    p_run.add_argument(
        "--smoke",
        action="store_true",
        help="after a successful apply, smoke-run touched entrypoint scripts "
        "(executes generated code; opt-in, see docs/safety.md)",
    )
    p_run.add_argument("--assume-clarification", action="store_true")
    p_run.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="answer the plan's clarifying questions interactively (requires a TTY); "
        "takes precedence over --assume-clarification",
    )
    p_run.add_argument("--evidence-file", action="append", default=[])
    p_run.add_argument("--evidence-stdin", action="store_true")
    p_run.add_argument(
        "--profile",
        default=None,
        help="select an llm_profiles entry from config.yaml for this invocation",
    )
    p_run.add_argument(
        "--max-patch-attempts",
        dest="max_patch_attempts",
        type=int,
        default=None,
        help="override cfg.safety.max_patch_attempts for this run only",
    )
    p_run.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="emit one JSON document on stdout (dry-run only); useful for scripting",
    )

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question")
    p_ask.add_argument("--evidence-file", action="append", default=[])
    p_ask.add_argument("--evidence-stdin", action="store_true")
    p_ask.add_argument(
        "--profile",
        default=None,
        help="select an llm_profiles entry from config.yaml for this invocation",
    )
    p_ask.add_argument("--rag", action="store_true")

    p_preview = sub.add_parser("preview")
    p_preview.add_argument("task")
    p_preview.add_argument("--evidence-file", action="append", default=[])
    p_preview.add_argument("--evidence-stdin", action="store_true")
    p_preview.add_argument(
        "--profile",
        default=None,
        help="select an llm_profiles entry from config.yaml for this invocation",
    )
    p_preview.add_argument("--rag", action="store_true")

    p_review = sub.add_parser("review")
    p_review.add_argument("--base", default="")
    p_review.add_argument("--head", default="HEAD")
    p_review.add_argument("--staged", action="store_true")
    p_review.add_argument("--diff-file", action="append", default=[])
    p_review.add_argument("--diff-stdin", action="store_true")
    p_review.add_argument(
        "--profile",
        default=None,
        help="select an llm_profiles entry from config.yaml for this invocation",
    )

    p_rag = sub.add_parser("rag")
    rag_sub = p_rag.add_subparsers(dest="rag_command", required=True)
    p_rag_index = rag_sub.add_parser("index")
    p_rag_index.add_argument("--rebuild", action="store_true")
    p_rag_query = rag_sub.add_parser("query")
    p_rag_query.add_argument("query")
    p_rag_query.add_argument("--top-k", type=int, default=None)

    p_runs = sub.add_parser("runs", help="manage .local-codex-lite/runs lifecycle")
    runs_sub = p_runs.add_subparsers(dest="runs_command", required=True)
    for runs_action in ("archive", "prune"):
        sp = runs_sub.add_parser(
            runs_action,
            help=("archive" if runs_action == "archive" else "archive + remove")
            + " runs older than N days",
        )
        sp.add_argument(
            "--older-than",
            dest="older_than",
            type=float,
            default=30.0,
            help="age threshold in days (default: 30)",
        )
        sp.add_argument(
            "--apply", action="store_true", help="actually archive/remove; default is dry-run"
        )
        if runs_action == "archive":
            sp.add_argument(
                "--remove",
                action="store_true",
                help="delete the run dir after archiving (= 'prune')",
            )
    p_runs_export = runs_sub.add_parser(
        "export",
        help="zip a single run on demand (bug-report friendly)",
    )
    p_runs_export.add_argument(
        "--run", default="latest", help="run id under .local-codex-lite/runs/, path, or 'latest'"
    )
    p_runs_export.add_argument(
        "--out", default=None, help="output zip path or directory (default: next to the run)"
    )

    p_replay = sub.add_parser("replay", help="re-run a saved task without calling the LLM")
    p_replay.add_argument("run_id", help="run id, path, or 'latest'")
    p_replay.add_argument(
        "--dry-run", action="store_true", help="print the cached plan + patch and exit"
    )
    p_replay.add_argument(
        "--apply", action="store_true", help="re-apply the saved patch to the current workspace"
    )
    p_replay.add_argument(
        "--profile",
        default=None,
        help="select an llm_profiles entry (affects only post-apply config, no LLM call)",
    )

    p_undo = sub.add_parser("undo", help="restore workspace files from a run's backups/")
    p_undo.add_argument(
        "--run", default="latest", help="run id under .local-codex-lite/runs/, or 'latest'"
    )
    p_undo.add_argument(
        "--apply", action="store_true", help="actually overwrite the workspace; default is dry-run"
    )

    p_plugins = sub.add_parser(
        "plugins",
        help="inspect capability plugins discovered via entry_points",
    )
    plugins_sub = p_plugins.add_subparsers(dest="plugins_command", required=True)
    p_plugins_list = plugins_sub.add_parser(
        "list",
        help="show every Capability the agent currently sees and its source",
    )
    p_plugins_list.add_argument(
        "--plugins-only",
        dest="plugins_only",
        action="store_true",
        help="show only entry-point contributed capabilities (drops built-ins)",
    )
    p_plugins_list.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="emit machine-readable JSON instead of the text table",
    )

    p_logs = sub.add_parser("logs")
    logs_sub = p_logs.add_subparsers(dest="logs_command", required=True)
    logs_sub.add_parser("latest")
    p_logs_tail = logs_sub.add_parser("tail")
    p_logs_tail.add_argument("--lines", type=int, default=40)
    p_logs_tail.add_argument("--run", default="latest")
    p_logs_show = logs_sub.add_parser("show")
    p_logs_show.add_argument("run_id")
    p_logs_diff = logs_sub.add_parser("diff", help="compare two runs side-by-side")
    p_logs_diff.add_argument("left", help="left run id, path, or 'latest'")
    p_logs_diff.add_argument("right", help="right run id, path, or 'latest'")

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
    p_th_scan.add_argument(
        "--image", default=os.environ.get("TRUFFLEHOG_IMAGE", "trufflesecurity/trufflehog:3.94.1")
    )
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

    p_cve_history = evidence_sub.add_parser(
        "cve-scan-history",
        help="list past cve-bin-tool scans by walking a directory tree",
    )
    p_cve_history.add_argument(
        "path", nargs="?", default=None, help="root to walk; defaults to .local-codex-lite/runs"
    )

    p_cve = evidence_sub.add_parser("cve-scan", help="CVE scan tool runner")
    p_cve.add_argument(
        "action_or_input", nargs="?", help="status | install | update-db | scan | <input_root>"
    )
    p_cve.add_argument(
        "input_root", nargs="?", help="Path to artifacts directory (may contain archives)"
    )
    p_cve.add_argument("--extract-to", dest="extract_to", default=None)
    p_cve.add_argument("--output-dir", dest="output_dir", default=None)
    p_cve.add_argument(
        "--install", action="store_true", help="Auto-install cve-bin-tool if missing"
    )
    p_cve.add_argument(
        "--update-db", dest="update_db", action="store_true", help="Update CVE database before scan"
    )
    p_cve.add_argument(
        "--skip-unpack", dest="skip_unpack", action="store_true", help="Skip archive extraction"
    )
    p_cve.add_argument("--offline", action="store_true", help="Run cve-bin-tool in offline mode")
    p_cve.add_argument(
        "--min-severity",
        dest="min_severity",
        default="HIGH",
        choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    )
    p_cve.add_argument("--format", default="json,md,high-critical-md")

    return parser

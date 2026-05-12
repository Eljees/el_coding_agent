"""CLI handlers for evidence sub-commands (artifacts, trufflehog, json-compare, cve-scan)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .artifact_unpack import inspect_artifacts, render_markdown_report, result_as_dict
from .evidence import compare_json_files
from .evidence_mode import (
    create_evidence_bundle,
    save_raw_json,
    save_report_text,
    save_summary_json,
    write_status,
)
from .logging_utils import dump_json, session_dir
from .trufflehog import analyze_output_root, compare_trufflehog_outputs, scan_repo_urls
from .cli_utils import console, load_urls, workspace_root


def cmd_evidence_json_compare(args: argparse.Namespace) -> int:
    comparison = compare_json_files(Path(args.left), Path(args.right))
    payload = {
        "left": args.left,
        "right": args.right,
        "same": comparison.same,
        "summary": comparison.summary,
        "changes": comparison.changes,
    }
    if args.out:
        dump_json(Path(args.out), payload)
    console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_evidence_artifacts_inspect(args: argparse.Namespace) -> int:
    root = workspace_root()
    run_dir = session_dir(root)
    source = Path(args.input_root)
    bundle = create_evidence_bundle(
        run_dir,
        source="artifacts",
        task=f"inspect artifacts {source}",
        run_id=run_dir.name,
    )
    extract_to_raw = getattr(args, "extract_to_flag", None) or getattr(args, "extract_to", None)
    try:
        result = inspect_artifacts(
            source,
            bundle.raw_dir,
            extract=bool(args.extract),
            extract_to=Path(extract_to_raw) if extract_to_raw else None,
            max_depth=args.max_depth,
            max_files=args.max_files,
            max_total_bytes=args.max_total_bytes,
        )
    except FileNotFoundError as exc:
        write_status(
            bundle,
            status="failed",
            error_code="source_not_found",
            message=str(exc),
            evidence_complete=False,
        )
        console.print("Artifact inspection failed: source_not_found")
        console.print(str(exc))
        console.print(f"Evidence: {bundle.bundle_dir}")
        return 1

    payload = result_as_dict(result)
    save_raw_json(bundle, "archive_inventory.json", payload)
    save_summary_json(bundle, "archive_summary.json", result.summary)
    save_report_text(bundle, "artifact_unpack_report.md", render_markdown_report(result))
    status = (
        "ok"
        if result.summary.get("archives_failed", 0) == 0
        and result.summary.get("archives_blocked", 0) == 0
        else "partial"
    )
    error_code = None if status == "ok" else "artifact_inspection_incomplete"
    write_status(
        bundle,
        status=status,
        error_code=error_code,
        message="artifact archive inspection completed",
        evidence_complete=True,
        extra={
            "archives_total": result.summary.get("archives_total", 0),
            "files_extracted": result.summary.get("files_extracted", 0),
            "extraction_root": result.extraction_root,
        },
    )
    console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
    console.print(f"Evidence: {bundle.bundle_dir}")
    return 0 if status == "ok" else 1


def cmd_evidence_trufflehog_scan(args: argparse.Namespace) -> int:
    urls = load_urls(args.repo_file, args.repo_url)
    if not urls:
        raise SystemExit("Provide at least one repo URL via --repo-url or --repo-file.")
    if not args.git_user or not args.git_token:
        raise SystemExit("Set GITLAB_USER/GITLAB_TOKEN or pass --git-user/--git-token.")
    cache_root = (
        Path(args.cache_root)
        if args.cache_root
        else workspace_root() / ".local-codex-lite" / "trufflehog_cache"
    )
    out_root = (
        Path(args.out_root)
        if args.out_root
        else workspace_root() / ".local-codex-lite" / "trufflehog_runs"
    )
    result = scan_repo_urls(
        urls,
        git_user=args.git_user,
        git_token=args.git_token,
        image=args.image,
        cache_root=cache_root,
        out_root=out_root,
        depth=args.depth,
        keep_clones=args.keep_clones,
    )
    dump_json(result.baseline_dir / "baseline_total.json", result.total)
    console.print_json(json.dumps(result.total, ensure_ascii=False, indent=2))
    if result.status and result.status.get("status") != "ok":
        console.print(f"Scan failed: {result.status.get('error_code', 'unknown')}")
        console.print(f"Reason: {result.status.get('detail') or result.status.get('message')}")
        console.print(f"Next: {result.status.get('suggested_action')}")
        console.print(f"Evidence: {result.evidence_dir or result.baseline_dir}")
    else:
        console.print(f"Evidence saved to: {result.baseline_dir}")
    return 1 if result.total.get("failures") else 0


def cmd_evidence_trufflehog_analyze(args: argparse.Namespace) -> int:
    report = analyze_output_root(Path(args.input_root))
    if args.out:
        dump_json(Path(args.out), report)
    console.print_json(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") != "ok":
        console.print(f"Scan failed: {report.get('error_code', 'unknown')}")
        console.print(f"Reason: {report.get('detail') or report.get('message')}")
        console.print(f"Next: {report.get('suggested_action')}")
        console.print(f"Evidence: {report.get('baseline_root')}")
        return 1
    return 0


def cmd_evidence_trufflehog_compare(args: argparse.Namespace) -> int:
    comparison = compare_trufflehog_outputs(Path(args.left), Path(args.right))
    payload = {"left": args.left, "right": args.right, **comparison}
    if args.out:
        dump_json(Path(args.out), payload)
    console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_evidence_cve_scan(args: argparse.Namespace) -> int:
    """Run cve-bin-tool CVE scan on an artifact directory via the skill script."""
    skill_script = Path(__file__).resolve().parent.parent.parent / "skills" / "cve-bin-tool" / "run_cve_scan.py"
    if not skill_script.exists():
        # Fallback: locate relative to workspace root
        root = workspace_root()
        skill_script = root / "skills" / "cve-bin-tool" / "run_cve_scan.py"
    if not skill_script.exists():
        console.print(f"[red]Skill script not found:[/red] {skill_script}")
        console.print("Expected: skills/cve-bin-tool/run_cve_scan.py")
        return 1

    cmd: list[str] = [sys.executable, str(skill_script), "--input-root", args.input_root]
    if getattr(args, "extract_to", None):
        cmd += ["--extract-to", args.extract_to]
    if getattr(args, "output_dir", None):
        cmd += ["--output-dir", args.output_dir]
    if getattr(args, "install", False):
        cmd.append("--install")
    if getattr(args, "update_db", False):
        cmd.append("--update-db")
    if getattr(args, "skip_unpack", False):
        cmd.append("--skip-unpack")
    if getattr(args, "min_severity", None):
        cmd += ["--min-severity", args.min_severity]

    console.print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    return result.returncode

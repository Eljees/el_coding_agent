"""CLI handlers for evidence sub-commands (artifacts, trufflehog, json-compare, cve-scan)."""
from __future__ import annotations

import argparse
import importlib.resources
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


def _candidate_exists(path: Path) -> bool:
    """Indirection used by resolve_cve_skill_script so tests can patch the
    existence check at a stable, module-level name regardless of pathlib's
    Path/PosixPath/WindowsPath internals."""
    return path.exists()


def resolve_cve_skill_script(root: Path | None = None) -> Path:
    """Return the path to run_cve_scan.py, or raise FileNotFoundError with diagnostics."""
    candidates: list[Path] = []
    package_root = Path(__file__).resolve().parents[1]
    candidates.append(package_root / "skills" / "cve-bin-tool" / "run_cve_scan.py")
    candidates.append(Path(__file__).resolve().parent / "skills" / "cve-bin-tool" / "run_cve_scan.py")
    if root is not None:
        candidates.append(root / "skills" / "cve-bin-tool" / "run_cve_scan.py")
    candidates.append(workspace_root() / "skills" / "cve-bin-tool" / "run_cve_scan.py")
    try:
        packaged = importlib.resources.files("local_codex_lite").joinpath(
            "skills", "cve-bin-tool", "run_cve_scan.py"
        )
        candidates.append(Path(str(packaged)))
    except Exception:
        pass
    for candidate in candidates:
        if _candidate_exists(candidate):
            return candidate
    searched = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        "CVE skill script 'run_cve_scan.py' not found. Searched:\n  "
        + searched
        + "\nMake sure 'skills/cve-bin-tool/run_cve_scan.py' exists in the project root."
    )


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
    try:
        skill_script = resolve_cve_skill_script()
    except FileNotFoundError as exc:
        console.print(f"[red]Skill script not found:[/red] {exc}")
        return 1

    action = "scan"
    input_root = getattr(args, "input_root", None)
    action_or_input = getattr(args, "action_or_input", None)
    if action_or_input in {"status", "install", "update-db", "scan"}:
        action = action_or_input
    elif action_or_input:
        input_root = action_or_input

    cmd: list[str] = [sys.executable, str(skill_script), action]
    if action == "scan":
        if not input_root:
            raise SystemExit(
                "Provide an artifact path or use one of: status, install, update-db, scan."
            )
        cmd.append(input_root)
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
        if getattr(args, "offline", False):
            cmd.append("--offline")
        if getattr(args, "min_severity", None):
            cmd += ["--min-severity", args.min_severity]
        if getattr(args, "format", None):
            cmd += ["--format", args.format]
    elif getattr(args, "offline", False):
        cmd.append("--offline")

    console.print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # Print captured output so it reaches GUI buffers (redirect_stdout) and the terminal.
    if result.stdout:
        console.print(result.stdout, end="")
    if result.stderr:
        console.print(result.stderr, end="", highlight=False)
    return result.returncode


def collect_cve_scan_history(search_root: Path) -> list[dict]:
    """Walk *search_root* recursively for ``cve_summary.json`` files and
    return a chronologically ordered list of summaries.

    Pure: does not touch the workspace.  Used both by the CLI handler
    below and by tests that inject a fake history tree.
    """
    history: list[dict] = []
    if not search_root.exists():
        return history
    for path in sorted(search_root.rglob("cve_summary.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        severity_counts = data.get("severity_counts") or {}
        history.append(
            {
                "summary_path": str(path),
                "generated_at": data.get("generated_at") or data.get("updated_at") or "",
                "artifact": data.get("artifact") or data.get("input_root") or "",
                "total_findings": data.get("total_findings", 0),
                "critical": severity_counts.get("CRITICAL", 0),
                "high": severity_counts.get("HIGH", 0),
                "medium": severity_counts.get("MEDIUM", 0),
                "status": data.get("status") or "",
            }
        )
    # Stable sort by generated_at so newest runs land at the bottom.
    history.sort(key=lambda item: item.get("generated_at") or "")
    return history


def cmd_evidence_cve_scan_history(args: argparse.Namespace) -> int:
    """Render an evidence-first history of past cve-bin-tool scans.

    Walks the directory in args.path (default ``<workspace>/.local-codex-lite/runs``)
    and prints one row per ``cve_summary.json`` found.  Returns 0 when at
    least one entry was rendered, 1 when nothing was found or the
    search root does not exist.
    """
    root = workspace_root()
    search_root = Path(args.path) if getattr(args, "path", None) else root / ".local-codex-lite" / "runs"
    if not search_root.exists():
        console.print(f"[red]No such directory:[/red] {search_root}")
        return 1
    history = collect_cve_scan_history(search_root)
    if not history:
        console.print(f"No cve_summary.json found under {search_root}.")
        return 1
    console.print(f"[bold]CVE scan history under {search_root}[/bold]")
    for entry in history:
        console.print(
            "- "
            f"{entry['generated_at'] or '—':<32} "
            f"total={entry['total_findings']:>4} "
            f"CRITICAL={entry['critical']:>3} "
            f"HIGH={entry['high']:>3} "
            f"MEDIUM={entry['medium']:>3} "
            f"status={entry['status'] or '—':<8} "
            f"| {entry['artifact'] or '—'}"
        )
        console.print(f"  evidence: {entry['summary_path']}")
    console.print(f"\n{len(history)} scan(s) total.")
    return 0

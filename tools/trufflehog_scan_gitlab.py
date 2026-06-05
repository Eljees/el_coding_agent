#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

from local_codex_lite.container_errors import classify_container_error

DEFAULT_IMAGE = "trufflesecurity/trufflehog:3.94.1"


def repo_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def run(
    cmd: list[str], *, cwd: Path | None = None, timeout: int = 1200
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def parse_ndjson(text: str) -> dict:
    if not text.strip():
        return {
            "findings": 0,
            "verified": 0,
            "unknown": 0,
            "unverified": 0,
            "detectors": {},
        }
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    detectors = Counter()
    verified = 0
    unknown = 0
    unverified = 0
    for row in rows:
        detectors[row.get("DetectorName", "unknown")] += 1
        if row.get("Verified") is True:
            verified += 1
        elif row.get("VerificationError"):
            unknown += 1
        else:
            unverified += 1
    return {
        "findings": len(rows),
        "verified": verified,
        "unknown": unknown,
        "unverified": unverified,
        "detectors": dict(detectors.most_common()),
    }


def clone_repo(url: str, dst: Path, user: str, token: str, depth: int) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    auth_url = url.replace("https://", f"https://{user}:{token}@")
    cp = run(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-c",
            "http.sslVerify=false",
            "clone",
            "--depth",
            str(depth),
            auth_url,
            str(dst),
        ],
        timeout=1800,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "git clone failed")


def scan_repo(repo_dir: Path, image: str) -> dict:
    cp = run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{repo_dir.resolve()}:/scanrepo",
            image,
            "git",
            "file:///scanrepo",
            "--no-update",
            "--no-verification",
            "--results=verified,unverified,unknown",
            "--json",
        ],
        timeout=2400,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "trufflehog failed")
    return parse_ndjson(cp.stdout)


def load_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    if args.repo_file:
        for raw in Path(args.repo_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    if args.repo_url:
        urls.extend(args.repo_url)
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clone GitLab repos and run TruffleHog baseline scans."
    )
    parser.add_argument("--repo-url", action="append", help="Repository URL; can be repeated.")
    parser.add_argument("--repo-file", help="Text file with one repository URL per line.")
    parser.add_argument("--git-user", default=os.environ.get("GITLAB_USER", "").strip())
    parser.add_argument("--git-token", default=os.environ.get("GITLAB_TOKEN", "").strip())
    parser.add_argument("--image", default=os.environ.get("TRUFFLEHOG_IMAGE", DEFAULT_IMAGE))
    parser.add_argument(
        "--cache-root",
        default=os.environ.get("TRUFFLEHOG_CACHE_ROOT", ""),
        help="Cache directory for clones and temporary artifacts.",
    )
    parser.add_argument(
        "--out-root",
        default=os.environ.get("TRUFFLEHOG_OUT_ROOT", ""),
        help="Output directory for the scan results.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Git clone depth to use for repository checkout.",
    )
    parser.add_argument(
        "--keep-clones", action="store_true", help="Keep cloned repos after the scan."
    )
    args = parser.parse_args()

    urls = load_urls(args)
    if not urls:
        raise SystemExit("Provide at least one repo URL via --repo-url or --repo-file.")
    if not args.git_user or not args.git_token:
        raise SystemExit("Set GITLAB_USER/GITLAB_TOKEN or pass --git-user/--git-token.")

    repo_root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cache_root = (
        Path(args.cache_root)
        if args.cache_root
        else repo_root / ".local-codex-lite" / "trufflehog_cache"
    )
    out_root = (
        Path(args.out_root)
        if args.out_root
        else repo_root / ".local-codex-lite" / "trufflehog_runs"
    )
    run_cache = cache_root / timestamp
    run_out = out_root / timestamp
    clones_dir = run_cache / "clones"
    baseline_dir = run_out / "baseline"
    clones_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    failures = 0
    first_issue: dict[str, object] | None = None
    for url in urls:
        name = repo_name(url)
        clone_path = clones_dir / name
        row: dict[str, object] = {
            "repo": name,
            "url": url,
            "clone_status": "failed",
            "scan_status": "failed",
            "findings": 0,
            "verified": 0,
            "unknown": 0,
            "unverified": 0,
            "detectors": {},
        }
        try:
            clone_repo(url, clone_path, args.git_user, args.git_token, args.depth)
            row["clone_status"] = "ok"
            stats = scan_repo(clone_path, args.image)
            row.update(stats)
            row["scan_status"] = "ok"
        except subprocess.CalledProcessError as exc:
            issue = classify_container_error(
                returncode=exc.returncode,
                stdout=exc.output or "",
                stderr=exc.stderr or "",
                stage="clone" if row["clone_status"] == "failed" else "scan",
            )
            row["error"] = _sanitize_error(exc.stderr or exc.output or "command failed")
            row["error_code"] = issue.code
            row["error_title"] = issue.title
            row["suggested_action"] = issue.suggested_action
            row["evidence_hint"] = issue.evidence_hint
            failures += 1
            if first_issue is None:
                first_issue = _issue_payload(issue)
        except Exception as exc:
            issue = classify_container_error(stderr=str(exc), stage="scan")
            row["error"] = _sanitize_error(str(exc))
            row["error_code"] = issue.code
            row["error_title"] = issue.title
            row["suggested_action"] = issue.suggested_action
            row["evidence_hint"] = issue.evidence_hint
            failures += 1
            if first_issue is None:
                first_issue = _issue_payload(issue)
        results.append(row)
        write_json(baseline_dir / f"{name}.json", row)

    summary_rows = []
    for row in results:
        summary_rows.append(
            {
                "repo": row["repo"],
                "url": row["url"],
                "findings": row.get("findings", 0),
                "verified": row.get("verified", 0),
                "unknown": row.get("unknown", 0),
                "unverified": row.get("unverified", 0),
                "clone_status": row.get("clone_status", "failed"),
                "scan_status": row.get("scan_status", "failed"),
                "top_detectors": row.get("detectors", {}),
            }
        )

    with (baseline_dir / "baseline_summary.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "repo",
                "url",
                "findings",
                "verified",
                "unknown",
                "unverified",
                "clone_status",
                "scan_status",
                "top_detectors",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    total = {
        "findings": sum(int(r.get("findings", 0)) for r in results),
        "verified": sum(int(r.get("verified", 0)) for r in results),
        "unknown": sum(int(r.get("unknown", 0)) for r in results),
        "unverified": sum(int(r.get("unverified", 0)) for r in results),
        "repos": len(results),
        "failures": failures,
    }
    write_json(baseline_dir / "baseline_total.json", total)
    write_json(
        baseline_dir / "manifest.json", {"timestamp": timestamp, "image": args.image, "urls": urls}
    )
    status = {
        "status": "ok" if failures == 0 else ("failed" if failures == len(results) else "partial"),
        "error_code": first_issue["error_code"] if first_issue else None,
        "message": "scan completed successfully"
        if failures == 0
        else f"{failures} repository scan(s) failed",
        "evidence_complete": failures == 0,
    }
    if first_issue:
        status.update(first_issue)
    write_json(baseline_dir / "status.json", status)

    if not args.keep_clones:
        shutil.rmtree(run_cache, ignore_errors=True)

    print(json.dumps(total, ensure_ascii=False))
    return 1 if failures else 0


def _issue_payload(issue) -> dict[str, object]:
    return {
        "error_code": issue.code,
        "title": issue.title,
        "detail": issue.detail,
        "retryable": issue.retryable,
        "suggested_action": issue.suggested_action,
        "evidence_hint": issue.evidence_hint,
    }


def _sanitize_error(text: str) -> str:
    return " ".join(text.split())[:500]


if __name__ == "__main__":
    raise SystemExit(main())

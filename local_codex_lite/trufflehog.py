from __future__ import annotations

import base64
import csv
import json
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from .container_errors import classify_container_error
from .evidence import compare_json_values_as_dict, save_json_file
from .evidence_mode import (
    create_evidence_bundle,
    save_raw_json,
    save_report_text,
    save_summary_json,
    write_status,
)
from .logging_utils import sanitize_log_text

DEFAULT_IMAGE = "trufflesecurity/trufflehog:3.94.1"


@dataclass(frozen=True)
class TruffleHogRunResult:
    total: dict[str, int]
    results: list[dict[str, object]]
    run_out: Path
    baseline_dir: Path
    evidence_dir: Path | None = None
    status: dict[str, object] | None = None


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


def parse_ndjson(text: str) -> dict[str, object]:
    if not text.strip():
        return {
            "findings": 0,
            "verified": 0,
            "unknown": 0,
            "unverified": 0,
            "detectors": {},
            "raw_findings": [],
        }
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    detectors: Counter[str] = Counter()
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
        "raw_findings": rows,
    }


_AUTH_HEADER_ARG_RE = re.compile(r"^http\.extraHeader=Authorization:\s*", re.IGNORECASE)


def _redact_subprocess_args(args: object) -> object:
    """Return *args* with any Authorization-bearing git config option masked.

    ``subprocess.CalledProcessError`` keeps the full argv around and prints it
    when the exception is rendered.  Without this hook, raising on a failed
    clone would surface the raw Basic-auth header (and therefore the token).
    """
    if not isinstance(args, (list, tuple)):
        return args
    redacted: list[object] = []
    for item in args:
        if isinstance(item, str) and _AUTH_HEADER_ARG_RE.match(item):
            redacted.append("http.extraHeader=Authorization: <redacted>")
        else:
            redacted.append(item)
    return type(args)(redacted)


def clone_repo(url: str, dst: Path, user: str, token: str, depth: int) -> None:
    """Clone *url* into *dst* using HTTP Basic auth supplied via
    ``http.extraHeader`` rather than embedding ``user:token`` in the URL.

    Embedding credentials in the URL makes them appear verbatim in any error
    output git produces (``fatal: unable to access 'https://USER:TOKEN@...'``)
    and in downstream tooling that records the cloned URL.  Passing them via
    ``-c http.extraHeader`` keeps the URL clean and lets us redact the args
    list before propagating a ``CalledProcessError``.
    """
    if dst.exists():
        shutil.rmtree(dst)
    basic = base64.b64encode(f"{user}:{token}".encode()).decode("ascii")
    cp = run(
        [
            "git",
            "-c",
            f"http.extraHeader=Authorization: Basic {basic}",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-c",
            "http.sslVerify=false",
            "clone",
            "--depth",
            str(depth),
            url,
            str(dst),
        ],
        timeout=1800,
    )
    if cp.returncode != 0:
        raise subprocess.CalledProcessError(
            cp.returncode,
            cast("list[str]", _redact_subprocess_args(cp.args)),
            output=cp.stdout,
            stderr=cp.stderr,
        )


def scan_repo(repo_dir: Path, image: str = DEFAULT_IMAGE) -> dict[str, object]:
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
        raise subprocess.CalledProcessError(
            cp.returncode, cp.args, output=cp.stdout, stderr=cp.stderr
        )
    return parse_ndjson(cp.stdout)


def scan_repo_urls(
    urls: Iterable[str],
    *,
    git_user: str,
    git_token: str,
    image: str = DEFAULT_IMAGE,
    cache_root: Path,
    out_root: Path,
    depth: int = 1,
    keep_clones: bool = False,
) -> TruffleHogRunResult:
    deduped_urls = _dedupe(urls)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_cache = cache_root / timestamp
    run_out = out_root / timestamp
    clones_dir = run_cache / "clones"
    baseline_dir = run_out / "baseline"
    evidence_bundle = create_evidence_bundle(
        run_out, source="trufflehog", task=f"scan {len(deduped_urls)} repos", run_id=timestamp
    )
    clones_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    save_raw_json(
        evidence_bundle,
        "manifest.json",
        {
            "timestamp": timestamp,
            "image": image,
            "urls": deduped_urls,
            "depth": depth,
        },
    )

    results: list[dict[str, object]] = []
    failures = 0
    first_issue: dict[str, object] | None = None
    for url in deduped_urls:
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
            clone_repo(url, clone_path, git_user, git_token, depth)
            row["clone_status"] = "ok"
            stats = scan_repo(clone_path, image)
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
        except json.JSONDecodeError as exc:
            issue = classify_container_error(stderr=str(exc), stage="scan")
            row["error"] = _sanitize_error(str(exc))
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
        save_json_file(baseline_dir / f"{name}.json", row)
        save_summary_json(evidence_bundle, f"{name}.json", row)

    summary_rows = [
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
        for row in results
    ]

    with (baseline_dir / "baseline_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
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
    save_report_text(evidence_bundle, "baseline_summary.csv", _summary_csv_text(summary_rows))

    total = {
        "findings": sum(int(cast(int, r.get("findings", 0))) for r in results),
        "verified": sum(int(cast(int, r.get("verified", 0))) for r in results),
        "unknown": sum(int(cast(int, r.get("unknown", 0))) for r in results),
        "unverified": sum(int(cast(int, r.get("unverified", 0))) for r in results),
        "repos": len(results),
        "failures": failures,
    }
    save_json_file(baseline_dir / "baseline_total.json", total)
    save_summary_json(evidence_bundle, "baseline_total.json", total)
    save_summary_json(
        evidence_bundle,
        "manifest.json",
        {"timestamp": timestamp, "image": image, "urls": deduped_urls, "depth": depth},
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
    write_status(
        evidence_bundle,
        status=cast(str, status["status"]),
        error_code=cast("str | None", status.get("error_code")),
        message=cast(str, status["message"]),
        evidence_complete=bool(status.get("evidence_complete")),
        extra={
            k: v
            for k, v in status.items()
            if k not in {"status", "error_code", "message", "evidence_complete"}
        },
    )

    if not keep_clones:
        shutil.rmtree(run_cache, ignore_errors=True)

    return TruffleHogRunResult(
        total=total,
        results=results,
        run_out=run_out,
        baseline_dir=baseline_dir,
        evidence_dir=evidence_bundle.bundle_dir,
        status=status,
    )


def analyze_output_root(input_root: Path) -> dict[str, object]:
    root = _baseline_root(input_root)
    manifest_path = root / "manifest.json"
    total_path = root / "baseline_total.json"
    summary_csv = root / "baseline_summary.csv"
    repo_jsons = sorted(
        path
        for path in root.glob("*.json")
        if path.name not in {"baseline_total.json", "manifest.json"}
    )
    if not root.exists() or (
        not repo_jsons
        and not total_path.exists()
        and not summary_csv.exists()
        and not manifest_path.exists()
    ):
        issue = classify_container_error(
            missing_artifacts=["baseline_total.json", "baseline_summary.csv", "repo_jsons"],
            stage="analyze",
        )
        return {
            "status": "failed",
            "error_code": issue.code,
            "title": issue.title,
            "detail": issue.detail,
            "retryable": issue.retryable,
            "suggested_action": issue.suggested_action,
            "evidence_hint": issue.evidence_hint,
            "input_root": str(input_root),
            "baseline_root": str(root),
            "manifest": {},
            "total": {},
            "repo_files": [],
            "repos": [],
            "summary_rows": [],
            "same_repo_count": 0,
            "detector_totals": {},
        }
    try:
        rows = [json.loads(path.read_text(encoding="utf-8")) for path in repo_jsons]
        summary_rows = _read_csv(summary_csv) if summary_csv.exists() else []
        total = json.loads(total_path.read_text(encoding="utf-8")) if total_path.exists() else {}
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        )
    except json.JSONDecodeError as exc:
        issue = classify_container_error(stderr=str(exc), stage="analyze")
        return {
            "status": "failed",
            "error_code": issue.code,
            "title": issue.title,
            "detail": issue.detail,
            "retryable": issue.retryable,
            "suggested_action": issue.suggested_action,
            "evidence_hint": issue.evidence_hint,
            "input_root": str(input_root),
            "baseline_root": str(root),
            "manifest": {},
            "total": {},
            "repo_files": [path.name for path in repo_jsons],
            "repos": [],
            "summary_rows": [],
            "same_repo_count": 0,
            "detector_totals": {},
        }
    return {
        "status": "ok",
        "input_root": str(input_root),
        "baseline_root": str(root),
        "manifest": manifest,
        "total": total,
        "repo_files": [path.name for path in repo_jsons],
        "repos": rows,
        "summary_rows": summary_rows,
        "same_repo_count": len(rows),
        "detector_totals": _aggregate_detectors(rows),
    }


def compare_trufflehog_outputs(left_root: Path, right_root: Path) -> dict[str, object]:
    left = analyze_output_root(left_root)
    right = analyze_output_root(right_root)
    return compare_json_values_as_dict(left, right)


def _baseline_root(input_root: Path) -> Path:
    candidate = input_root / "baseline"
    return candidate if candidate.exists() else input_root


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _aggregate_detectors(rows: list[dict[str, object]]) -> dict[str, int]:
    detectors: Counter[str] = Counter()
    for row in rows:
        raw = row.get("detectors", {})
        if isinstance(raw, dict):
            for key, value in raw.items():
                detectors[str(key)] += int(value)
    return dict(detectors.most_common())


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _issue_payload(issue) -> dict[str, object]:
    return {
        "error_code": issue.code,
        "title": issue.title,
        "detail": issue.detail,
        "retryable": issue.retryable,
        "suggested_action": issue.suggested_action,
        "evidence_hint": issue.evidence_hint,
    }


_AUTH_URL_RE = re.compile(r"(https?://)[^/\s@]+:[^/\s@]+@", re.IGNORECASE)
_AUTH_HEADER_BODY_RE = re.compile(r"(authorization:\s*basic\s+)\S+", re.IGNORECASE)


def _sanitize_error(text: str) -> str:
    """Redact common credential shapes (url-embedded basic auth, Authorization
    headers) and delegate the rest to the project-wide log sanitizer."""
    masked = _AUTH_URL_RE.sub(r"\1<redacted>:<redacted>@", text or "")
    masked = _AUTH_HEADER_BODY_RE.sub(r"\1<redacted>", masked)
    return sanitize_log_text(masked, limit=500)


def _summary_csv_text(summary_rows: list[dict[str, object]]) -> str:
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
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
    return buffer.getvalue()

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from local_codex_lite.trufflehog import (
    _redact_subprocess_args,
    analyze_output_root,
    compare_trufflehog_outputs,
    parse_ndjson,
    scan_repo_urls,
)


def test_analyze_output_root_reads_baseline_dir(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "repo-a.json").write_text(
        '{"repo": "repo-a", "findings": 2, "detectors": {"AWSKey": 2}}',
        encoding="utf-8",
    )
    (baseline / "baseline_total.json").write_text(
        '{"findings": 2, "verified": 0, "unknown": 0, "unverified": 2, "repos": 1, "failures": 0}',
        encoding="utf-8",
    )
    (baseline / "manifest.json").write_text(
        '{"timestamp": "t", "image": "img", "urls": ["u"]}', encoding="utf-8"
    )
    (baseline / "baseline_summary.csv").write_text(
        "repo,url,findings,verified,unknown,unverified,clone_status,scan_status,top_detectors\n"
        "repo-a,u,2,0,0,2,ok,ok,{'AWSKey': 2}\n",
        encoding="utf-8",
    )

    report = analyze_output_root(tmp_path)

    assert report["total"]["findings"] == 2
    assert report["same_repo_count"] == 1
    assert report["detector_totals"]["AWSKey"] == 2


def test_scan_repo_urls_writes_evidence(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_clone(url: str, dst: Path, user: str, token: str, depth: int) -> None:
        calls.append(("clone", url))
        dst.mkdir(parents=True, exist_ok=True)

    def fake_scan(
        repo_dir: Path, image: str = "trufflesecurity/trufflehog:3.94.1"
    ) -> dict[str, object]:
        calls.append(("scan", repo_dir.name))
        return {
            "findings": 1,
            "verified": 1,
            "unknown": 0,
            "unverified": 0,
            "detectors": {"AWSKey": 1},
            "raw_findings": [],
        }

    monkeypatch.setattr("local_codex_lite.trufflehog.clone_repo", fake_clone)
    monkeypatch.setattr("local_codex_lite.trufflehog.scan_repo", fake_scan)

    result = scan_repo_urls(
        ["https://example.com/a.git"],
        git_user="user",
        git_token="token",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
        keep_clones=True,
    )

    assert result.total["findings"] == 1
    assert result.baseline_dir.exists()
    assert (result.baseline_dir / "a.json").exists()
    assert calls[0][0] == "clone"
    assert calls[1][0] == "scan"


# ---------------------------------------------------------------------------
# parse_ndjson
# ---------------------------------------------------------------------------


def test_parse_ndjson_empty_text_returns_zeroes() -> None:
    result = parse_ndjson("")
    assert result["findings"] == 0
    assert result["verified"] == 0
    assert result["unknown"] == 0
    assert result["unverified"] == 0
    assert result["raw_findings"] == []
    assert result["detectors"] == {}


def test_parse_ndjson_whitespace_only_returns_zeroes() -> None:
    assert parse_ndjson("   \n  ")["findings"] == 0


def test_parse_ndjson_with_findings() -> None:
    line1 = json.dumps({"DetectorName": "AWSKey", "Verified": True})
    line2 = json.dumps({"DetectorName": "Slack", "Verified": False, "VerificationError": "timeout"})
    line3 = json.dumps({"DetectorName": "GitHub", "Verified": False})
    result = parse_ndjson(f"{line1}\n{line2}\n{line3}")
    assert result["findings"] == 3
    assert result["verified"] == 1
    assert result["unknown"] == 1  # has VerificationError
    assert result["unverified"] == 1
    assert result["detectors"]["AWSKey"] == 1
    assert result["detectors"]["Slack"] == 1


def test_parse_ndjson_unknown_detector_name() -> None:
    line = json.dumps({"Verified": False})  # no DetectorName
    result = parse_ndjson(line)
    assert result["findings"] == 1
    assert "unknown" in result["detectors"]


# ---------------------------------------------------------------------------
# _redact_subprocess_args
# ---------------------------------------------------------------------------


def test_redact_subprocess_args_masks_auth_header() -> None:
    args = [
        "git",
        "-c",
        "http.extraHeader=Authorization: Basic supersecrettoken",
        "clone",
        "https://repo.example.com/project.git",
    ]
    redacted = list(_redact_subprocess_args(args))
    joined = " ".join(str(a) for a in redacted)
    assert "supersecrettoken" not in joined
    assert "<redacted>" in joined


def test_redact_subprocess_args_leaves_non_auth_items_unchanged() -> None:
    args = ["git", "clone", "https://example.com/repo.git", "--depth", "1"]
    assert list(_redact_subprocess_args(args)) == args


def test_redact_subprocess_args_handles_non_list_input() -> None:
    assert _redact_subprocess_args("not a list") == "not a list"
    assert _redact_subprocess_args(42) == 42  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# scan_repo_urls failure paths
# ---------------------------------------------------------------------------


def test_scan_repo_urls_removes_clones_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("local_codex_lite.trufflehog.clone_repo", lambda *a, **kw: None)
    monkeypatch.setattr(
        "local_codex_lite.trufflehog.scan_repo",
        lambda *a, **kw: {
            "findings": 0,
            "verified": 0,
            "unknown": 0,
            "unverified": 0,
            "detectors": {},
            "raw_findings": [],
        },
    )
    result = scan_repo_urls(
        ["https://example.com/r.git"],
        git_user="u",
        git_token="t",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
        keep_clones=False,  # default behaviour
    )
    assert result.baseline_dir.exists()
    # The cache/clones tree must have been pruned.
    cache_root = tmp_path / "cache"
    leftover = list(cache_root.rglob("*")) if cache_root.exists() else []
    assert leftover == []


def test_scan_repo_urls_clone_failure_recorded(tmp_path: Path, monkeypatch) -> None:
    def fail_clone(url: str, dst: Path, user: str, token: str, depth: int) -> None:
        raise subprocess.CalledProcessError(128, ["git", "clone"], output="", stderr="auth error")

    monkeypatch.setattr("local_codex_lite.trufflehog.clone_repo", fail_clone)

    result = scan_repo_urls(
        ["https://bad.example.com/r.git"],
        git_user="u",
        git_token="t",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
    )
    assert result.total["failures"] == 1
    row = result.results[0]
    assert row["clone_status"] == "failed"
    assert row["scan_status"] == "failed"


def test_scan_repo_urls_json_decode_error_recorded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "local_codex_lite.trufflehog.clone_repo",
        lambda url, dst, user, token, depth: dst.mkdir(parents=True, exist_ok=True),
    )

    def bad_scan(repo_dir: Path, image: str = "") -> dict[str, object]:
        raise json.JSONDecodeError("bad json", "", 0)

    monkeypatch.setattr("local_codex_lite.trufflehog.scan_repo", bad_scan)

    result = scan_repo_urls(
        ["https://example.com/r.git"],
        git_user="u",
        git_token="t",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
    )
    assert result.total["failures"] == 1


def test_scan_repo_urls_generic_exception_recorded(tmp_path: Path, monkeypatch) -> None:
    def bad_clone(url: str, dst: Path, user: str, token: str, depth: int) -> None:
        raise RuntimeError("something unexpected")

    monkeypatch.setattr("local_codex_lite.trufflehog.clone_repo", bad_clone)

    result = scan_repo_urls(
        ["https://bad.example.com/r.git"],
        git_user="u",
        git_token="t",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
    )
    assert result.total["failures"] == 1


# ---------------------------------------------------------------------------
# analyze_output_root edge cases
# ---------------------------------------------------------------------------


def test_analyze_output_root_missing_dir_returns_failed(tmp_path: Path) -> None:
    empty = tmp_path / "empty_run"
    empty.mkdir()
    result = analyze_output_root(empty)
    assert result["status"] == "failed"
    assert result["repos"] == []


def test_analyze_output_root_corrupt_repo_json(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "repo-a.json").write_text("not valid json", encoding="utf-8")
    (baseline / "baseline_total.json").write_text('{"findings": 0}', encoding="utf-8")
    result = analyze_output_root(tmp_path)
    assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# compare_trufflehog_outputs
# ---------------------------------------------------------------------------


def test_compare_trufflehog_outputs_returns_dict(tmp_path: Path) -> None:
    left = tmp_path / "left"
    left.mkdir()
    right = tmp_path / "right"
    right.mkdir()
    result = compare_trufflehog_outputs(left, right)
    # Both roots have no artifacts → both analyses are "failed"; diff is a dict
    assert isinstance(result, dict)

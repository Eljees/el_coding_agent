"""Additional coverage for cli_evidence.py — json-compare, artifacts, trufflehog,
and cve-scan edge cases."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_codex_lite.cli_evidence import (
    cmd_evidence_artifacts_inspect,
    cmd_evidence_cve_scan,
    cmd_evidence_json_compare,
    cmd_evidence_trufflehog_analyze,
    cmd_evidence_trufflehog_compare,
    cmd_evidence_trufflehog_scan,
)

# ---------------------------------------------------------------------------
# cmd_evidence_json_compare — full happy path (lines 63-74)
# ---------------------------------------------------------------------------


def test_cmd_evidence_json_compare_prints_comparison(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"a": 1}', encoding="utf-8")
    right.write_text('{"a": 2}', encoding="utf-8")

    args = argparse.Namespace(left=str(left), right=str(right), out=None)
    rc = cmd_evidence_json_compare(args)
    assert rc == 0


def test_cmd_evidence_json_compare_writes_out_file(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    out = tmp_path / "result.json"
    left.write_text('{"a": 1}', encoding="utf-8")
    right.write_text('{"a": 1}', encoding="utf-8")

    args = argparse.Namespace(left=str(left), right=str(right), out=str(out))
    rc = cmd_evidence_json_compare(args)
    assert rc == 0
    assert out.exists()


# ---------------------------------------------------------------------------
# cmd_evidence_artifacts_inspect — FileNotFoundError branch (lines 98-109)
# ---------------------------------------------------------------------------


def test_cmd_evidence_artifacts_inspect_source_not_found(tmp_path: Path) -> None:
    args = argparse.Namespace(
        input_root=str(tmp_path / "nonexistent"),
        extract=False,
        extract_to_flag=None,
        extract_to=None,
        max_depth=5,
        max_files=1000,
        max_total_bytes=100_000_000,
    )
    with patch("local_codex_lite.cli_evidence.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_evidence.session_dir", return_value=tmp_path / "run"):
            with patch("local_codex_lite.cli_evidence.create_evidence_bundle") as mock_bundle:
                fake_bundle = MagicMock()
                fake_bundle.raw_dir = tmp_path / "raw"
                fake_bundle.bundle_dir = tmp_path / "bundle"
                mock_bundle.return_value = fake_bundle
                with patch(
                    "local_codex_lite.cli_evidence.inspect_artifacts",
                    side_effect=FileNotFoundError("source not found"),
                ):
                    with patch("local_codex_lite.cli_evidence.write_status"):
                        rc = cmd_evidence_artifacts_inspect(args)
    assert rc == 1


# ---------------------------------------------------------------------------
# cmd_evidence_trufflehog_scan — full function (lines 140-174)
# ---------------------------------------------------------------------------


def test_cmd_evidence_trufflehog_scan_ok(tmp_path: Path) -> None:
    args = argparse.Namespace(
        repo_file=None,
        repo_url=["https://example.com/repo.git"],
        git_user="user",
        git_token="token",
        image="trufflehog:latest",
        cache_root=None,
        out_root=None,
        depth=50,
        keep_clones=False,
    )
    fake_result = MagicMock()
    fake_result.total = {"failures": 0}
    fake_result.baseline_dir = tmp_path / "baseline"
    fake_result.baseline_dir.mkdir()
    fake_result.status = {"status": "ok"}
    fake_result.evidence_dir = None

    with patch("local_codex_lite.cli_evidence.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_evidence.scan_repo_urls", return_value=fake_result):
            rc = cmd_evidence_trufflehog_scan(args)
    assert rc == 0


def test_cmd_evidence_trufflehog_scan_failures_returns_1(tmp_path: Path) -> None:
    args = argparse.Namespace(
        repo_file=None,
        repo_url=["https://example.com/repo.git"],
        git_user="user",
        git_token="token",
        image="trufflehog:latest",
        cache_root=str(tmp_path / "cache"),
        out_root=str(tmp_path / "out"),
        depth=50,
        keep_clones=False,
    )
    fake_result = MagicMock()
    fake_result.total = {"failures": 2}
    fake_result.baseline_dir = tmp_path / "baseline"
    fake_result.baseline_dir.mkdir()
    fake_result.status = {
        "status": "error",
        "error_code": "auth_missing",
        "detail": "auth",
        "message": "auth",
        "suggested_action": "fix auth",
    }
    fake_result.evidence_dir = tmp_path / "evidence"

    with patch("local_codex_lite.cli_evidence.scan_repo_urls", return_value=fake_result):
        rc = cmd_evidence_trufflehog_scan(args)
    assert rc == 1


# ---------------------------------------------------------------------------
# cmd_evidence_trufflehog_analyze — failure path (lines 178-188)
# ---------------------------------------------------------------------------


def test_cmd_evidence_trufflehog_analyze_ok(tmp_path: Path) -> None:
    args = argparse.Namespace(input_root=str(tmp_path), out=None)
    with patch(
        "local_codex_lite.cli_evidence.analyze_output_root",
        return_value={"status": "ok", "findings": []},
    ):
        rc = cmd_evidence_trufflehog_analyze(args)
    assert rc == 0


def test_cmd_evidence_trufflehog_analyze_failure_returns_1(tmp_path: Path) -> None:
    args = argparse.Namespace(input_root=str(tmp_path), out=None)
    with patch(
        "local_codex_lite.cli_evidence.analyze_output_root",
        return_value={
            "status": "failed",
            "error_code": "clone_failed",
            "detail": "git clone failed",
            "message": "error",
            "suggested_action": "check creds",
            "baseline_root": str(tmp_path),
        },
    ):
        rc = cmd_evidence_trufflehog_analyze(args)
    assert rc == 1


def test_cmd_evidence_trufflehog_analyze_writes_out_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    args = argparse.Namespace(input_root=str(tmp_path), out=str(out))
    with patch(
        "local_codex_lite.cli_evidence.analyze_output_root",
        return_value={"status": "ok"},
    ):
        rc = cmd_evidence_trufflehog_analyze(args)
    assert rc == 0
    assert out.exists()


# ---------------------------------------------------------------------------
# cmd_evidence_trufflehog_compare — full function (lines 192-197)
# ---------------------------------------------------------------------------


def test_cmd_evidence_trufflehog_compare_ok(tmp_path: Path) -> None:
    args = argparse.Namespace(left=str(tmp_path), right=str(tmp_path), out=None)
    with patch(
        "local_codex_lite.cli_evidence.compare_trufflehog_outputs",
        return_value={"added": [], "removed": []},
    ):
        rc = cmd_evidence_trufflehog_compare(args)
    assert rc == 0


def test_cmd_evidence_trufflehog_compare_writes_out_file(tmp_path: Path) -> None:
    out = tmp_path / "compare.json"
    args = argparse.Namespace(left=str(tmp_path), right=str(tmp_path), out=str(out))
    with patch(
        "local_codex_lite.cli_evidence.compare_trufflehog_outputs",
        return_value={"added": [], "removed": []},
    ):
        rc = cmd_evidence_trufflehog_compare(args)
    assert rc == 0
    assert out.exists()


# ---------------------------------------------------------------------------
# cmd_evidence_cve_scan — no input_root for scan action (line 219)
# ---------------------------------------------------------------------------


def test_cmd_evidence_cve_scan_raises_when_scan_has_no_input(tmp_path: Path) -> None:
    args = argparse.Namespace(
        action_or_input="scan",
        input_root=None,
        extract_to=None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=False,
        min_severity=None,
        format=None,
    )
    with patch(
        "local_codex_lite.cli_evidence.resolve_cve_skill_script", return_value=tmp_path / "fake.py"
    ):
        with pytest.raises(SystemExit, match="Provide an artifact path"):
            cmd_evidence_cve_scan(args)


# ---------------------------------------------------------------------------
# cmd_evidence_cve_scan — non-scan action with offline flag (line 240)
# ---------------------------------------------------------------------------


def test_cmd_evidence_cve_scan_non_scan_action_with_offline(tmp_path: Path) -> None:
    fake_script = tmp_path / "run_cve_scan.py"
    fake_script.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    args = argparse.Namespace(
        action_or_input="status",
        input_root=None,
        extract_to=None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=True,
        min_severity=None,
        format=None,
    )
    with patch("local_codex_lite.cli_evidence.resolve_cve_skill_script", return_value=fake_script):
        import subprocess as _sub

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""
        with patch("local_codex_lite.cli_evidence.subprocess.run", return_value=fake_proc):
            rc = cmd_evidence_cve_scan(args)
    assert rc == 0

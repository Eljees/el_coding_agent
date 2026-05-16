"""Tests for `local_codex_lite evidence cve-scan-history`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_codex_lite import cli
from local_codex_lite.cli_evidence import (
    cmd_evidence_cve_scan_history,
    collect_cve_scan_history,
)


def _write_summary(
    out_dir: Path,
    *,
    generated_at: str,
    artifact: str,
    total: int,
    critical: int,
    high: int,
    medium: int = 0,
    status: str = "ok",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "artifact": artifact,
        "total_findings": total,
        "severity_counts": {"CRITICAL": critical, "HIGH": high, "MEDIUM": medium},
        "status": status,
    }
    p = out_dir / "cve_summary.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# collect_cve_scan_history
# ---------------------------------------------------------------------------

def test_collect_empty_when_no_summaries(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    assert collect_cve_scan_history(tmp_path) == []


def test_collect_returns_each_summary(tmp_path: Path) -> None:
    _write_summary(tmp_path / "runA", generated_at="2026-05-10T01:00:00+00:00",
                   artifact="A", total=5, critical=1, high=2)
    _write_summary(tmp_path / "runB", generated_at="2026-05-11T01:00:00+00:00",
                   artifact="B", total=0, critical=0, high=0)
    history = collect_cve_scan_history(tmp_path)
    assert len(history) == 2
    # Sorted oldest-first
    assert history[0]["artifact"] == "A"
    assert history[1]["artifact"] == "B"
    assert history[0]["critical"] == 1
    assert history[0]["high"] == 2


def test_collect_ignores_malformed_summary(tmp_path: Path) -> None:
    bad = tmp_path / "runX" / "cve_summary.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("not json at all", encoding="utf-8")
    good = _write_summary(tmp_path / "runOK", generated_at="2026-05-12T00:00:00+00:00",
                          artifact="OK", total=0, critical=0, high=0)
    history = collect_cve_scan_history(tmp_path)
    assert len(history) == 1
    assert history[0]["summary_path"] == str(good)


def test_collect_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert collect_cve_scan_history(tmp_path / "does-not-exist") == []


# ---------------------------------------------------------------------------
# cmd_evidence_cve_scan_history
# ---------------------------------------------------------------------------

def test_cmd_history_returns_1_for_missing_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("local_codex_lite.cli_evidence.workspace_root", lambda: tmp_path)
    code = cmd_evidence_cve_scan_history(argparse.Namespace(path=str(tmp_path / "nope")))
    assert code == 1


def test_cmd_history_returns_1_when_nothing_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("local_codex_lite.cli_evidence.workspace_root", lambda: tmp_path)
    # Default path: workspace/.local-codex-lite/runs -- must exist but be empty
    runs = tmp_path / ".local-codex-lite" / "runs"
    runs.mkdir(parents=True)
    code = cmd_evidence_cve_scan_history(argparse.Namespace(path=None))
    assert code == 1


def test_cmd_history_prints_table(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_summary(tmp_path / "runA", generated_at="2026-05-10T01:00:00+00:00",
                   artifact="contentreader-nls.rpm", total=7, critical=2, high=5)
    monkeypatch.setattr("local_codex_lite.cli_evidence.workspace_root", lambda: tmp_path)
    code = cmd_evidence_cve_scan_history(argparse.Namespace(path=str(tmp_path)))
    out = capsys.readouterr().out
    assert code == 0
    assert "contentreader-nls.rpm" in out
    assert "total=   7" in out
    assert "CRITICAL=  2" in out
    assert "HIGH=  5" in out


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def test_build_parser_cve_scan_history() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["evidence", "cve-scan-history"])
    assert ns.command == "evidence"
    assert ns.evidence_command == "cve-scan-history"
    assert ns.path is None


def test_build_parser_cve_scan_history_explicit_path() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["evidence", "cve-scan-history", "D:/cve_evidence"])
    assert ns.path == "D:/cve_evidence"

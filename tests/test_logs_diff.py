"""Tests for `local_codex_lite logs diff` — side-by-side run comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from local_codex_lite import cli, cli_logs


def _make_run(tmp_path: Path, run_id: str, *, task: str, applied: bool, plan_summary: str) -> Path:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "task.txt").write_text(task, encoding="utf-8")
    result = {"applied": applied}
    if not applied:
        result["failure"] = {"stage": "apply"}
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps({"summary": plan_summary}), encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def test_build_parser_logs_diff() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["logs", "diff", "runA", "runB"])
    assert ns.command == "logs"
    assert ns.logs_command == "diff"
    assert ns.left == "runA"
    assert ns.right == "runB"


# ---------------------------------------------------------------------------
# cmd_logs_diff
# ---------------------------------------------------------------------------


def test_cmd_logs_diff_returns_1_for_missing_left(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    rc = cli.cmd_logs_diff(argparse.Namespace(left="nope", right="latest"))
    assert rc == 1


def test_cmd_logs_diff_returns_1_for_missing_right(tmp_path: Path, monkeypatch) -> None:
    _make_run(tmp_path, "20260516-010101-000000-aaa", task="t", applied=True, plan_summary="p")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    rc = cli.cmd_logs_diff(argparse.Namespace(left="latest", right="missing"))
    assert rc == 1


def test_cmd_logs_diff_prints_both_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    left = _make_run(
        tmp_path, "20260516-010101-000000-aaa", task="task A", applied=True, plan_summary="plan-A"
    )
    right = _make_run(
        tmp_path, "20260516-020202-000000-bbb", task="task B", applied=False, plan_summary="plan-B"
    )
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    rc = cli.cmd_logs_diff(argparse.Namespace(left=left.name, right=right.name))
    out = capsys.readouterr().out
    assert rc == 0
    # Both tasks shown
    assert "task A" in out
    assert "task B" in out
    # Differing statuses surfaced
    assert "applied" in out
    assert "failed" in out
    # Differing plan summaries surfaced
    assert "plan-A" in out
    assert "plan-B" in out


def test_cmd_logs_diff_lists_artifact_diff(tmp_path: Path, monkeypatch, capsys) -> None:
    """Files present in one run but not the other should appear in the
    'artifacts only left/right' sections."""
    left = _make_run(
        tmp_path, "20260516-010101-000000-aaa", task="t", applied=True, plan_summary="p"
    )
    right = _make_run(
        tmp_path, "20260516-020202-000000-bbb", task="t", applied=True, plan_summary="p"
    )
    (left / "left-only.diff").write_text("LEFT", encoding="utf-8")
    (right / "right-only.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    rc = cli.cmd_logs_diff(argparse.Namespace(left=left.name, right=right.name))
    out = capsys.readouterr().out
    assert rc == 0
    assert "left-only.diff" in out
    assert "right-only.json" in out

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from local_codex_lite import cli, cli_logs


def test_logs_tail_falls_back_without_events(tmp_path: Path, monkeypatch, capsys) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    run_dir = runs / "20260501-010101"
    evidence = run_dir / "evidence"
    evidence.mkdir(parents=True)
    (run_dir / "task.txt").write_text("Add README", encoding="utf-8")
    (run_dir / "result.json").write_text('{"dry_run": true}', encoding="utf-8")
    (run_dir / "plan.json").write_text('{"summary": "plan"}', encoding="utf-8")
    (evidence / "status.json").write_text(
        '{"status": "ok", "error_code": null, "message": "done", "evidence_complete": true}',
        encoding="utf-8",
    )
    (evidence / "metadata.json").write_text('{"kind": "evidence_bundle"}', encoding="utf-8")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)

    result = cli.cmd_logs_tail(argparse.Namespace(lines=5, run="latest"))

    out = capsys.readouterr().out
    assert result == 0
    assert "No events.jsonl found" in out
    assert "evidence_status" in out


def test_logs_show_includes_evidence_status(tmp_path: Path, monkeypatch, capsys) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    run_dir = runs / "20260501-020202"
    evidence = run_dir / "evidence"
    evidence.mkdir(parents=True)
    (run_dir / "task.txt").write_text("Add README", encoding="utf-8")
    (run_dir / "result.json").write_text('{"applied": true}', encoding="utf-8")
    (run_dir / "plan.json").write_text('{"summary": "plan"}', encoding="utf-8")
    (evidence / "status.json").write_text(
        '{"status": "ok", "error_code": null, "message": "done", "evidence_complete": true}',
        encoding="utf-8",
    )
    (evidence / "metadata.json").write_text('{"kind": "evidence_bundle"}', encoding="utf-8")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)

    result = cli.cmd_logs_show(argparse.Namespace(run_id="latest"))

    out = capsys.readouterr().out
    assert result == 0
    assert "Task: Add README" in out
    assert "Evidence status: ok" in out


def test_logs_attempts_dispatch_routes_to_handler(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_ensure_utf8_output", lambda: None)
    monkeypatch.setattr(cli, "cmd_logs_attempts", lambda *a, **k: 4242)
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", "logs", "attempts"])
    assert cli.main() == 4242


def test_logs_attempts_defaults_to_latest_run(tmp_path: Path, monkeypatch, capsys) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    run_dir = runs / "20260501-030303"
    run_dir.mkdir(parents=True)
    (run_dir / "task.txt").write_text("Fix the histogram", encoding="utf-8")
    (run_dir / "result.json").write_text('{"applied": true}', encoding="utf-8")
    events = [
        {"stage": "plan", "attempt": 1, "status": "success"},
        {
            "stage": "apply",
            "status": "patch_error",
            "patch_error_code": "apply_failed",
            "raw_error": "error: corrupt patch at line 5",
            "repair_attempt": 1,
        },
        {"stage": "patch", "attempt": 2, "status": "success"},
    ]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)

    result = cli.cmd_logs_attempts(argparse.Namespace(run_id="latest"))

    out = capsys.readouterr().out
    assert result == 0
    assert "run: 20260501-030303" in out
    assert "task: Fix the histogram" in out
    assert "plan #1 ok" in out
    assert "apply #1 FAILED apply_failed: error: corrupt patch at line 5" in out
    assert "result: applied after 1 repair" in out


def test_logs_attempts_no_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    result = cli.cmd_logs_attempts(argparse.Namespace(run_id="latest"))
    assert result == 1
    assert "No matching run found." in capsys.readouterr().out

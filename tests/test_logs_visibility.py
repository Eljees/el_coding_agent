from __future__ import annotations

import argparse
from pathlib import Path

from local_codex_lite import cli


def test_logs_tail_falls_back_without_events(tmp_path: Path, monkeypatch, capsys) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    run_dir = runs / "20260501-010101"
    evidence = run_dir / "evidence"
    evidence.mkdir(parents=True)
    (run_dir / "task.txt").write_text("Add README", encoding="utf-8")
    (run_dir / "result.json").write_text('{"dry_run": true}', encoding="utf-8")
    (run_dir / "plan.json").write_text('{"summary": "plan"}', encoding="utf-8")
    (evidence / "status.json").write_text('{"status": "ok", "error_code": null, "message": "done", "evidence_complete": true}', encoding="utf-8")
    (evidence / "metadata.json").write_text('{"kind": "evidence_bundle"}', encoding="utf-8")
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)

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
    (evidence / "status.json").write_text('{"status": "ok", "error_code": null, "message": "done", "evidence_complete": true}', encoding="utf-8")
    (evidence / "metadata.json").write_text('{"kind": "evidence_bundle"}', encoding="utf-8")
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)

    result = cli.cmd_logs_show(argparse.Namespace(run_id="latest"))

    out = capsys.readouterr().out
    assert result == 0
    assert "Task: Add README" in out
    assert "Evidence status: ok" in out

from __future__ import annotations

import argparse
from pathlib import Path

from local_codex_lite import cli, cli_logs
from local_codex_lite.logging_utils import latest_events_path, latest_session_dir


def test_latest_session_dir_prefers_latest_run(tmp_path: Path) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    (runs / "20260430-010101").mkdir(parents=True)
    (runs / "20260430-020202").mkdir(parents=True)

    latest = latest_session_dir(tmp_path)

    assert latest is not None
    assert latest.name == "20260430-020202"


def test_latest_events_path_points_to_events_jsonl(tmp_path: Path) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    latest = runs / "20260430-020202"
    latest.mkdir(parents=True)
    events = latest / "events.jsonl"
    events.write_text('{"stage":"plan"}\n', encoding="utf-8")

    assert latest_events_path(tmp_path) == events


def test_cmd_logs_latest_prints_events(tmp_path: Path, monkeypatch, capsys) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    latest = runs / "20260430-020202"
    latest.mkdir(parents=True)
    events = latest / "events.jsonl"
    events.write_text('{"stage":"plan"}\n', encoding="utf-8")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)

    result = cli.cmd_logs_latest(argparse.Namespace())

    captured = capsys.readouterr().out
    assert result == 0
    assert "Latest run:" in captured
    assert '{"stage":"plan"}' in captured

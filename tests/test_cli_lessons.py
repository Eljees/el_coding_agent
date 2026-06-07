"""Coverage for the ``lessons`` CLI: dispatch routing plus list/stats/clear handlers."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pytest

from local_codex_lite import cli, cli_lessons, lessons


@pytest.fixture(autouse=True)
def _quiet_utf8(monkeypatch):
    monkeypatch.setattr(cli, "_ensure_utf8_output", lambda: None)


def _route(monkeypatch, argv: list[str], handler_name: str) -> int:
    sentinel = 4242
    monkeypatch.setattr(cli, handler_name, lambda *a, **k: sentinel)
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", *argv])
    return cli.main()


@pytest.mark.parametrize(
    "argv,handler",
    [
        (["lessons", "list"], "cmd_lessons_list"),
        (["lessons", "stats"], "cmd_lessons_stats"),
        (["lessons", "clear"], "cmd_lessons_clear"),
    ],
)
def test_lessons_dispatch_routes_to_handler(monkeypatch, argv, handler) -> None:
    assert _route(monkeypatch, argv, handler) == 4242


def test_lessons_list_empty(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_lessons, "workspace_root", lambda: tmp_path)
    rc = cli_lessons.cmd_lessons_list(argparse.Namespace())
    assert rc == 0
    assert "No learned lessons" in capsys.readouterr().out


def test_lessons_list_renders_records(tmp_path: Path, monkeypatch, capsys) -> None:
    lessons.record_lesson(
        tmp_path,
        error_code="python_syntax_error",
        detail="SyntaxError: invalid syntax at line 3",
        task="add a histogram helper",
    )
    monkeypatch.setattr(cli_lessons, "workspace_root", lambda: tmp_path)
    rc = cli_lessons.cmd_lessons_list(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "python_syntax_error" in out
    assert "histogram" in out


def test_lessons_stats_empty(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_lessons, "workspace_root", lambda: tmp_path)
    rc = cli_lessons.cmd_lessons_stats(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "No learned lessons recorded yet." in out
    assert "runs scanned: 0" in out


def test_lessons_stats_renders_verdicts(tmp_path: Path, monkeypatch, capsys) -> None:
    detail = "ValueError: boom"
    signature = lessons.signature_for_detail(detail)
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20200101-000000"
    run_dir.mkdir(parents=True)
    event = {
        "stage": "apply",
        "status": "patch_error",
        "patch_error_code": "apply_failed",
        "raw_error": detail,
        "repair_attempt": 1,
    }
    (run_dir / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    (run_dir / "result.json").write_text('{"applied": true}', encoding="utf-8")
    store = tmp_path / ".local-codex-lite" / "lessons.jsonl"
    records = [
        # Recorded long after the failing run: the signature never recurred.
        {"ts": time.time(), "error_code": "apply_failed", "signature": signature},
        # Recorded before the failing run: the signature came back -> recurring.
        {"ts": 0.0, "error_code": "apply_failed", "signature": signature},
    ]
    store.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    monkeypatch.setattr(cli_lessons, "workspace_root", lambda: tmp_path)

    rc = cli_lessons.cmd_lessons_stats(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "✓ holding" in out
    assert "✗ recurring" in out
    assert "repair successes: 1" in out


def test_lessons_clear(tmp_path: Path, monkeypatch, capsys) -> None:
    lessons.record_lesson(tmp_path, error_code="c", detail="ValueError boom", task="t")
    monkeypatch.setattr(cli_lessons, "workspace_root", lambda: tmp_path)
    rc = cli_lessons.cmd_lessons_clear(argparse.Namespace())
    assert rc == 0
    assert "Cleared 1" in capsys.readouterr().out
    assert lessons.load_learned(tmp_path) == []

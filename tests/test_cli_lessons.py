"""Coverage for the ``lessons`` CLI: dispatch routing plus list/clear handlers."""

from __future__ import annotations

import argparse
import sys
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


def test_lessons_clear(tmp_path: Path, monkeypatch, capsys) -> None:
    lessons.record_lesson(tmp_path, error_code="c", detail="ValueError boom", task="t")
    monkeypatch.setattr(cli_lessons, "workspace_root", lambda: tmp_path)
    rc = cli_lessons.cmd_lessons_clear(argparse.Namespace())
    assert rc == 0
    assert "Cleared 1" in capsys.readouterr().out
    assert lessons.load_learned(tmp_path) == []

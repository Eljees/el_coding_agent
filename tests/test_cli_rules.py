"""Coverage for the ``rules`` CLI: dispatch routing plus show/init handlers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from local_codex_lite import cli, cli_rules, lessons


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
        (["rules", "show"], "cmd_rules_show"),
        (["rules", "init"], "cmd_rules_init"),
    ],
)
def test_rules_dispatch_routes_to_handler(monkeypatch, argv, handler) -> None:
    assert _route(monkeypatch, argv, handler) == 4242


def test_rules_show_no_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_rules, "workspace_root", lambda: tmp_path)
    rc = cli_rules.cmd_rules_show(argparse.Namespace())
    assert rc == 0
    assert "no AGENT_RULES.md" in capsys.readouterr().out


def test_rules_show_file_without_rules(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / lessons.RULES_FILENAME).write_text("# only a heading\n", encoding="utf-8")
    monkeypatch.setattr(cli_rules, "workspace_root", lambda: tmp_path)
    rc = cli_rules.cmd_rules_show(argparse.Namespace())
    assert rc == 0
    assert "no rules" in capsys.readouterr().out


def test_rules_show_renders_parsed_rules(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / lessons.RULES_FILENAME).write_text(
        "# heading\n- answer in Russian\n* no new dependencies\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli_rules, "workspace_root", lambda: tmp_path)
    rc = cli_rules.cmd_rules_show(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0
    assert "User rules (2)" in out
    assert "answer in Russian" in out
    assert "no new dependencies" in out


def test_rules_init_creates_template(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_rules, "workspace_root", lambda: tmp_path)
    rc = cli_rules.cmd_rules_init(argparse.Namespace())
    assert rc == 0
    assert "Created" in capsys.readouterr().out
    path = tmp_path / lessons.RULES_FILENAME
    assert path.exists()
    assert path.read_text(encoding="utf-8") == cli_rules.RULES_TEMPLATE
    # The template's example bullets are valid, parseable rules.
    assert lessons.load_user_rules(tmp_path)


def test_rules_init_refuses_to_overwrite(tmp_path: Path, monkeypatch, capsys) -> None:
    existing = tmp_path / lessons.RULES_FILENAME
    existing.write_text("- my precious rule\n", encoding="utf-8")
    monkeypatch.setattr(cli_rules, "workspace_root", lambda: tmp_path)
    rc = cli_rules.cmd_rules_init(argparse.Namespace())
    assert rc == 1
    assert "already exists" in capsys.readouterr().out
    assert existing.read_text(encoding="utf-8") == "- my precious rule\n"

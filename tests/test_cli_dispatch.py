"""Coverage for the cli.main() command dispatcher.

main() is a large if/elif over args.command; this drives the routing for each
top-level command with the actual handlers stubbed, so a mis-wired branch (or a
re-export that silently disappeared) fails loudly.
"""

from __future__ import annotations

import sys

import pytest

from local_codex_lite import cli


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
        (["init"], "cmd_init"),
        (["status"], "cmd_status"),
        (["recognize", "t"], "cmd_recognize"),
        (["ask", "q"], "cmd_ask"),
        (["preview", "t"], "cmd_preview"),
        (["review"], "cmd_review"),
        (["run", "t"], "_run_task"),
        (["rag", "query", "q"], "cmd_rag_query"),
        (["rag", "index"], "cmd_rag_index"),
        (["logs", "latest"], "cmd_logs_latest"),
        (["logs", "diff", "a", "b"], "cmd_logs_diff"),
        (["doctor"], "cmd_doctor"),
        (["doctor", "deps"], "cmd_doctor_deps"),
    ],
)
def test_dispatch_routes_to_handler(monkeypatch, argv, handler) -> None:
    assert _route(monkeypatch, argv, handler) == 4242


def test_no_command_prints_help_and_returns_1(monkeypatch, capsys) -> None:
    # argparse requires a subcommand; an unknown one exits with code 2.
    monkeypatch.setattr(sys, "argv", ["local-codex-lite"])
    with pytest.raises(SystemExit):
        cli.main()

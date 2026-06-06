"""Dispatch coverage for the remaining cli.main() branches.

test_cli_dispatch.py drives the common commands; this module covers the rest
of the routing table (ui, doctor rag, config show, runs, replay, undo,
plugins, logs tail/show, the evidence family), the small handler bodies
cmd_ui / cmd_doctor / cmd_doctor_deps, the help fallback and the
``python -m``-style entrypoint line.
"""

from __future__ import annotations

import argparse
import runpy
import sys
import warnings
from pathlib import Path

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
        (["config", "show"], "cmd_config_show"),
        (["runs", "archive"], "cmd_runs_archive"),
        (["runs", "prune"], "cmd_runs_prune"),
        (["runs", "export"], "cmd_runs_export"),
        (["replay", "latest"], "cmd_replay"),
        (["undo"], "cmd_undo"),
        (["plugins", "list"], "cmd_plugins_list"),
        (["logs", "tail"], "cmd_logs_tail"),
        (["logs", "show", "run-1"], "cmd_logs_show"),
        (["evidence", "json-compare", "left.json", "right.json"], "cmd_evidence_json_compare"),
        (["evidence", "artifacts", "inspect", "."], "cmd_evidence_artifacts_inspect"),
        (["evidence", "trufflehog", "scan"], "cmd_evidence_trufflehog_scan"),
        (["evidence", "trufflehog", "analyze", "in"], "cmd_evidence_trufflehog_analyze"),
        (["evidence", "trufflehog", "compare", "a", "b"], "cmd_evidence_trufflehog_compare"),
        (["evidence", "cve-scan"], "cmd_evidence_cve_scan"),
        (["evidence", "cve-scan-history"], "cmd_evidence_cve_scan_history"),
    ],
)
def test_dispatch_routes_remaining_commands(monkeypatch, argv, handler) -> None:
    assert _route(monkeypatch, argv, handler) == 4242


def test_dispatch_ui_invokes_command_center(monkeypatch) -> None:
    seen: dict[str, int | None] = {}

    def fake_ui(autoclose_ms=None):
        seen["autoclose_ms"] = autoclose_ms
        return 0

    monkeypatch.setattr(cli, "run_command_center_ui", fake_ui)
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", "ui", "--autoclose-ms", "5"])

    assert cli.main() == 0
    assert seen["autoclose_ms"] == 5


def test_dispatch_doctor_rag(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "run_rag_doctor", lambda root: 0 if root == tmp_path else 1)
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", "doctor", "rag"])

    assert cli.main() == 0


def test_cmd_doctor_runs_core_doctor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "run_doctor", lambda root: 0 if root == tmp_path else 1)

    assert cli.cmd_doctor(argparse.Namespace()) == 0


def test_cmd_doctor_deps_runs_dependency_doctor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "run_dependency_doctor", lambda root: 0 if root == tmp_path else 1)

    assert cli.cmd_doctor_deps(argparse.Namespace()) == 0


def test_unmatched_command_prints_help_and_returns_1(monkeypatch, capsys) -> None:
    """All argparse choices are wired, so the fallback is only reachable when
    the parser produces a command main() does not know about."""

    class _FakeParser:
        def parse_args(self) -> argparse.Namespace:
            return argparse.Namespace(command="bogus")

        def print_help(self) -> None:
            print("usage: local-codex-lite")

    monkeypatch.setattr(cli, "build_parser", lambda: _FakeParser())

    assert cli.main() == 1
    assert "usage: local-codex-lite" in capsys.readouterr().out


def test_cli_module_entrypoint_raises_systemexit(monkeypatch, capsys) -> None:
    """Running ``cli`` as a script must funnel main()'s return code into
    SystemExit.  ``recognize`` is fully offline, so the real main() is safe."""
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", "recognize", "doctor"])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("local_codex_lite.cli", run_name="__main__")

    assert exc_info.value.code == 0

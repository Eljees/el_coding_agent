"""CLI smoke tests for the non-LLM command surface.

These tests do not require a vLLM endpoint.  They exercise the import
graph plus the dispatch / output / file-I/O paths so a broken release
gets caught before anyone tries to ``run`` a task.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from local_codex_lite import cli, cli_info, cli_logs
from local_codex_lite.config import config_path


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


# ---------------------------------------------------------------------------
# init / status / config show
# ---------------------------------------------------------------------------


def test_cmd_init_creates_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_info, "workspace_root", lambda: tmp_path)
    code = cli.cmd_init(_ns())
    assert code == 0
    assert config_path(tmp_path).exists()


def test_cmd_init_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_info, "workspace_root", lambda: tmp_path)
    cli.cmd_init(_ns())
    code = cli.cmd_init(_ns())
    assert code == 0


def test_cmd_status_prints_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_info, "workspace_root", lambda: tmp_path)
    code = cli.cmd_status(_ns())
    captured = capsys.readouterr().out
    assert code == 0
    assert "Workspace:" in captured
    assert "LLM:" in captured


def test_cmd_config_show_redacts_secrets(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_info, "workspace_root", lambda: tmp_path)
    code = cli.cmd_config_show(_ns())
    captured = capsys.readouterr().out
    assert code == 0
    # Every key matching the sensitive-name heuristic (api_key, token, ...)
    # must be redacted.  The default config has llm.api_key so look for the
    # marker rather than the literal default value.
    assert "<redacted>" in captured


# ---------------------------------------------------------------------------
# recognize
# ---------------------------------------------------------------------------


def test_cmd_recognize_routes_logs_latest_phrase(capsys) -> None:
    code = cli.cmd_recognize(_ns(task="покажи последние логи"))
    captured = capsys.readouterr().out
    assert code == 0
    assert "logs.latest" in captured


def test_cmd_recognize_routes_trufflehog_scan_missing_input(capsys) -> None:
    code = cli.cmd_recognize(_ns(task="запусти trufflehog scan"))
    captured = capsys.readouterr().out
    assert code == 0
    assert "evidence.trufflehog.scan" in captured
    # Without a URL/file the JSON must surface the missing input.
    assert "repo_url_or_file" in captured


def test_cmd_recognize_empty_task_returns_needs_input(capsys) -> None:
    code = cli.cmd_recognize(_ns(task=""))
    captured = capsys.readouterr().out
    assert code == 0
    assert "needs_input" in captured


# ---------------------------------------------------------------------------
# logs latest / tail / show
# ---------------------------------------------------------------------------


def test_cmd_logs_latest_returns_1_when_no_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    code = cli.cmd_logs_latest(_ns())
    assert code == 1


def test_cmd_logs_latest_prints_events_when_present(tmp_path: Path, monkeypatch, capsys) -> None:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260515-010101"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text('{"stage":"plan"}\n', encoding="utf-8")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    code = cli.cmd_logs_latest(_ns())
    captured = capsys.readouterr().out
    assert code == 0
    assert "Latest run:" in captured
    assert '"stage":"plan"' in captured


def test_cmd_logs_tail_returns_1_for_missing_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    code = cli.cmd_logs_tail(_ns(run="latest", lines=10))
    assert code == 1


def test_cmd_logs_show_returns_1_for_missing_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    code = cli.cmd_logs_show(_ns(run_id="latest"))
    assert code == 1


def test_cmd_logs_show_renders_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260515-020202"
    run_dir.mkdir(parents=True)
    (run_dir / "task.txt").write_text("hello", encoding="utf-8")
    (run_dir / "result.json").write_text('{"applied": true}', encoding="utf-8")
    (run_dir / "patch.diff").write_text("diff --git a/x b/x\n", encoding="utf-8")
    monkeypatch.setattr(cli_logs, "workspace_root", lambda: tmp_path)
    code = cli.cmd_logs_show(_ns(run_id="latest"))
    captured = capsys.readouterr().out
    assert code == 0
    assert "Run:" in captured
    assert "Status:" in captured


# ---------------------------------------------------------------------------
# argparse + dispatch via main()
# ---------------------------------------------------------------------------


def test_main_dispatch_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr("sys.argv", ["local-codex-lite", "status"])
    assert cli.main() == 0


def test_main_dispatch_recognize(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["local-codex-lite", "recognize", "doctor"])
    rc = cli.main()
    captured = capsys.readouterr().out
    assert rc == 0
    assert "doctor" in captured


def test_build_parser_exec_dest_is_execute() -> None:
    """Regression for stage 3a: --exec must populate args.execute, not args.exec."""
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "task", "--apply", "--exec"])
    assert getattr(ns, "execute", None) is True
    assert not hasattr(ns, "exec")


def test_build_parser_max_patch_attempts_override() -> None:
    """The --max-patch-attempts flag must populate args.max_patch_attempts."""
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "task", "--apply", "--max-patch-attempts", "9"])
    assert ns.max_patch_attempts == 9


def test_build_parser_max_patch_attempts_default_is_none() -> None:
    """Without --max-patch-attempts the runner must fall back to the config
    default, which is signaled by the attribute being None."""
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "task", "--apply"])
    assert ns.max_patch_attempts is None


def test_build_parser_doctor_full() -> None:
    """``doctor full`` must route to the aggregate health-check command."""
    parser = cli.build_parser()
    ns = parser.parse_args(["doctor", "full"])
    assert ns.command == "doctor"
    assert ns.doctor_command == "full"


def test_main_doctor_full_invokes_run_full_doctor(tmp_path: Path, monkeypatch) -> None:
    """``main()`` -> doctor dispatch -> run_full_doctor with the workspace root.

    We monkeypatch run_full_doctor to a sentinel so the test stays offline
    (real doctor hits the LLM endpoint and shells out to git / docker).
    """
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)
    called = {}

    def fake_full(root):
        called["root"] = root
        return 0

    monkeypatch.setattr(cli, "run_full_doctor", fake_full)
    monkeypatch.setattr("sys.argv", ["local-codex-lite", "doctor", "full"])
    assert cli.main() == 0
    assert called["root"] == tmp_path

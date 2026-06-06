"""Tests for ``local_codex_lite.ui_runners``.

All tests are Tkinter-free — that's the whole point of extracting
the worker functions into a separate module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from local_codex_lite.ui_runners import (
    _capture,
    _fmt,
    artifact_worker,
    cve_worker,
    initial_progress_message,
    logs_latest_worker,
    preview_worker,
    redirect_optional_stdin,
    run_worker,
)

# ---------------------------------------------------------------------------
# redirect_optional_stdin
# ---------------------------------------------------------------------------


def test_redirect_optional_stdin_empty_leaves_stdin_unchanged() -> None:
    original = sys.stdin
    with redirect_optional_stdin(""):
        assert sys.stdin is original


def test_redirect_optional_stdin_nonempty_patches_stdin() -> None:
    import io

    original = sys.stdin
    with redirect_optional_stdin("hello evidence"):
        patched = sys.stdin
        assert patched is not original
        assert patched.read() == "hello evidence"
    # Restored after the block.
    assert sys.stdin is original


def test_redirect_optional_stdin_restores_on_exception() -> None:
    original = sys.stdin
    with pytest.raises(RuntimeError):
        with redirect_optional_stdin("data"):
            assert sys.stdin is not original
            raise RuntimeError("boom")
    assert sys.stdin is original


# ---------------------------------------------------------------------------
# _fmt
# ---------------------------------------------------------------------------


def test_fmt_with_output_and_zero_code_returns_output_only() -> None:
    result = _fmt("some output", 0, "Preview")
    assert result == "some output"


def test_fmt_with_output_and_nonzero_code_appends_exit_code() -> None:
    result = _fmt("some output", 2, "Preview")
    assert "some output" in result
    assert "(exit code: 2)" in result


def test_fmt_with_no_output_returns_finished_message() -> None:
    result = _fmt("", 0, "Logs latest")
    assert "Logs latest" in result
    assert "exit code" in result


# ---------------------------------------------------------------------------
# initial_progress_message
# ---------------------------------------------------------------------------


def test_initial_progress_message_non_cve_label(tmp_path: Path) -> None:
    msg = initial_progress_message("preview", "fix the bug", tmp_path)
    assert "preview" in msg
    assert str(tmp_path) in msg
    assert "CVE" not in msg


def test_initial_progress_message_cve_label_includes_stages(tmp_path: Path) -> None:
    task = "scan /tmp/firmware.zip for CVE severity MEDIUM"
    msg = initial_progress_message("cve scan", task, tmp_path)
    assert "CVE scan started." in msg
    assert "stage=run cve-bin-tool" in msg
    assert "min_severity=" in msg


def test_initial_progress_message_cve_no_artifact_path(tmp_path: Path) -> None:
    # Even when the task has no recognisable artifact path, the message must
    # not crash — it just reports input='-'.
    msg = initial_progress_message("cve scan", "do a cve scan", tmp_path)
    assert "input=-" in msg


# ---------------------------------------------------------------------------
# _capture helper
# ---------------------------------------------------------------------------


def test_capture_redirects_stdout(tmp_path: Path) -> None:
    def emit_hello(args):
        print("hello from fn")
        return 0

    import argparse

    output, code = _capture(emit_hello, argparse.Namespace(), tmp_path)
    assert output == "hello from fn"
    assert code == 0


def test_capture_redirects_stderr(tmp_path: Path) -> None:
    import sys as _sys

    def emit_stderr(args):
        print("err text", file=_sys.stderr)
        return 1

    import argparse

    output, code = _capture(emit_stderr, argparse.Namespace(), tmp_path)
    assert "err text" in output
    assert code == 1


# ---------------------------------------------------------------------------
# preview_worker
# ---------------------------------------------------------------------------


def test_preview_worker_returns_output(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(cli_mod, "cmd_preview", lambda args: (print("preview ok"), 0)[1])
    result = preview_worker("fix bug", tmp_path, "")
    assert "preview ok" in result


def test_preview_worker_no_output_returns_finished(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(cli_mod, "cmd_preview", lambda args: 0)
    result = preview_worker("fix bug", tmp_path, "")
    assert "Preview" in result
    assert "exit code" in result


def test_preview_worker_with_evidence_patches_stdin(tmp_path: Path, monkeypatch) -> None:
    """When evidence_text is provided, cmd_preview sees it on sys.stdin."""
    import local_codex_lite.cli as cli_mod

    captured_stdin: list[str] = []

    def fake_preview(args):
        captured_stdin.append(sys.stdin.read())
        return 0

    monkeypatch.setattr(cli_mod, "cmd_preview", fake_preview)
    preview_worker("fix bug", tmp_path, "MY EVIDENCE")
    assert captured_stdin == ["MY EVIDENCE"]


# ---------------------------------------------------------------------------
# logs_latest_worker
# ---------------------------------------------------------------------------


def test_logs_latest_worker_returns_output(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(cli_mod, "cmd_logs_latest", lambda args: (print("log line"), 0)[1])
    result = logs_latest_worker(tmp_path)
    assert "log line" in result


def test_logs_latest_worker_no_output_returns_finished(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(cli_mod, "cmd_logs_latest", lambda args: 0)
    result = logs_latest_worker(tmp_path)
    assert "Logs latest" in result


# ---------------------------------------------------------------------------
# artifact_worker
# ---------------------------------------------------------------------------


def test_artifact_worker_no_path_returns_early(tmp_path: Path, monkeypatch) -> None:
    """When extract_artifact_input_path returns None, return an error string."""
    monkeypatch.setattr(
        "local_codex_lite.ui_runners.extract_artifact_input_path", lambda task: None
    )
    result = artifact_worker("some task", tmp_path, extract=False)
    assert "not found" in result.lower()


def test_artifact_worker_calls_cli(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(
        "local_codex_lite.ui_runners.extract_artifact_input_path", lambda task: "/tmp/fw.zip"
    )
    monkeypatch.setattr(
        "local_codex_lite.ui_runners.extract_artifact_output_path", lambda task: None
    )
    monkeypatch.setattr(
        cli_mod, "cmd_evidence_artifacts_inspect", lambda args: (print("inspect ok"), 0)[1]
    )
    result = artifact_worker("inspect /tmp/fw.zip", tmp_path, extract=False)
    assert "inspect ok" in result


# ---------------------------------------------------------------------------
# cve_worker
# ---------------------------------------------------------------------------


def test_cve_worker_no_path_returns_early(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "local_codex_lite.ui_runners.extract_artifact_input_path", lambda task: None
    )
    result = cve_worker("scan for cve", tmp_path)
    assert "not found" in result.lower()


def test_cve_worker_calls_cli(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(
        "local_codex_lite.ui_runners.extract_artifact_input_path", lambda task: "/tmp/fw.zip"
    )
    monkeypatch.setattr(
        "local_codex_lite.ui_runners.extract_artifact_output_path", lambda task: None
    )
    monkeypatch.setattr(
        "local_codex_lite.ui_runners.cve_min_severity_for_task", lambda task: "MEDIUM"
    )
    monkeypatch.setattr(cli_mod, "cmd_evidence_cve_scan", lambda args: (print("cve ok"), 0)[1])
    result = cve_worker("cve scan /tmp/fw.zip", tmp_path)
    assert "cve ok" in result


# ---------------------------------------------------------------------------
# run_worker
# ---------------------------------------------------------------------------


def test_run_worker_returns_output(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_run_task", lambda task, args: (print("run ok"), 0)[1])
    result = run_worker("fix bug", tmp_path, "", apply=False, exec_=False)
    assert "run ok" in result


def test_run_worker_with_evidence_patches_stdin(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    captured: list[str] = []

    def fake_run(task, args):
        captured.append(sys.stdin.read())
        return 0

    monkeypatch.setattr(cli_mod, "_run_task", fake_run)
    run_worker("fix bug", tmp_path, "EVIDENCE TEXT", apply=False, exec_=False)
    assert captured == ["EVIDENCE TEXT"]


def test_run_worker_no_output_returns_finished(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_run_task", lambda task, args: 0)
    result = run_worker("fix bug", tmp_path, "", apply=True, exec_=True)
    assert "Run" in result
    assert "exit code" in result

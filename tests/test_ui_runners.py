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


# ---------------------------------------------------------------------------
# chat_worker
# ---------------------------------------------------------------------------


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def test_chat_worker_prepends_system_prompt_and_strips_answer(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.config as config_mod
    import local_codex_lite.llm_client as llm_mod
    from local_codex_lite.ui_runners import CHAT_SYSTEM_PROMPT, chat_worker

    seen_messages: list[list[dict[str, str]]] = []

    class _FakeClient:
        def __init__(self, llm_config) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            seen_messages.append(messages)
            return _FakeLLMResponse("  the answer  \n")

    monkeypatch.setattr(config_mod, "load_config", lambda root: config_mod.AgentConfig())
    monkeypatch.setattr(llm_mod, "OpenAICompatibleClient", _FakeClient)
    answer = chat_worker([{"role": "user", "content": "hi"}], tmp_path)
    assert answer == "the answer"
    assert seen_messages[0][0] == {"role": "system", "content": CHAT_SYSTEM_PROMPT}
    assert seen_messages[0][1] == {"role": "user", "content": "hi"}


def test_chat_worker_renders_errors_inline(tmp_path: Path, monkeypatch) -> None:
    import local_codex_lite.config as config_mod
    from local_codex_lite.ui_runners import chat_worker

    def boom(root):
        raise RuntimeError("config exploded")

    monkeypatch.setattr(config_mod, "load_config", boom)
    answer = chat_worker([{"role": "user", "content": "hi"}], tmp_path)
    assert answer == "[Error: config exploded]"


# ---------------------------------------------------------------------------
# Status bar probes
# ---------------------------------------------------------------------------


def test_probe_cve_status_reports_version(monkeypatch) -> None:
    import subprocess

    from local_codex_lite.ui_runners import probe_cve_status

    class _Result:
        stdout = "CVE Binary Tool v3.4\nextra line"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    assert probe_cve_status() == "cve-bin-tool: CVE Binary Tool v3.4"


def test_probe_cve_status_falls_back_to_stderr_then_ok(monkeypatch) -> None:
    import subprocess

    from local_codex_lite.ui_runners import probe_cve_status

    class _Result:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    assert probe_cve_status() == "cve-bin-tool: ok"


def test_probe_cve_status_not_found(monkeypatch) -> None:
    import subprocess

    from local_codex_lite.ui_runners import probe_cve_status

    def raise_not_found(*a, **k):
        raise FileNotFoundError("no cve-bin-tool")

    monkeypatch.setattr(subprocess, "run", raise_not_found)
    assert probe_cve_status() == "cve-bin-tool: not found"


def test_probe_cve_status_generic_error(monkeypatch) -> None:
    import subprocess

    from local_codex_lite.ui_runners import probe_cve_status

    def raise_timeout(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert probe_cve_status() == "cve-bin-tool: error"


def test_probe_llm_status_ok(tmp_path: Path, monkeypatch) -> None:
    import urllib.request
    from types import SimpleNamespace

    import local_codex_lite.config as config_mod
    from local_codex_lite.ui_runners import probe_llm_status

    fake_cfg = SimpleNamespace(llm=SimpleNamespace(base_url="http://example:9000/v1"))
    monkeypatch.setattr(config_mod, "load_config", lambda root: fake_cfg)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=4: object())
    assert probe_llm_status(tmp_path) == "LLM: http://example:9000/v1 ok"


def test_probe_llm_status_unreachable_uses_default_url(tmp_path: Path, monkeypatch) -> None:
    import urllib.request

    import local_codex_lite.config as config_mod
    from local_codex_lite.ui_runners import probe_llm_status

    def config_boom(root):
        raise RuntimeError("no config")

    def urlopen_boom(url, timeout=4):
        raise OSError("connection refused")

    monkeypatch.setattr(config_mod, "load_config", config_boom)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen_boom)
    assert probe_llm_status(tmp_path) == "LLM: http://localhost:8015/v1 (unreachable)"

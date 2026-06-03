from __future__ import annotations

import argparse
from pathlib import Path

from local_codex_lite import cli, cli_review


class _DummyResponse:
    def __init__(
        self,
        text: str = '{"summary": "ok", "overall_risk": "low", "findings": [], "positives": [], "missing_context": [], "recommendation": "approve"}',
    ) -> None:
        self.text = text
        self.raw = {"model": "qwen25-coder-14b-awq"}


class _DummyClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages, status_label=None, max_tokens=None):
        self.calls.append(messages)
        return _DummyResponse()


def test_cmd_review_uses_diff_file(monkeypatch, tmp_path: Path, capsys) -> None:
    diff_file = tmp_path / "review.diff"
    diff_file.write_text(
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_make_review(task, diff_text, root, cfg, run_dir=None, extra_context=""):
        captured["task"] = task
        captured["diff_text"] = diff_text
        captured["context"] = extra_context
        return {
            "summary": "ok",
            "overall_risk": "low",
            "findings": [],
            "positives": ["diff loaded"],
            "missing_context": [],
            "recommendation": "approve",
        }

    monkeypatch.setattr(cli_review, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli_review, "load_config", lambda root: cli.default_config())
    monkeypatch.setattr(cli_review, "make_review", fake_make_review)
    monkeypatch.setattr(
        cli_review, "session_dir", lambda root: tmp_path / ".local-codex-lite" / "runs" / "test-run"
    )
    monkeypatch.setattr(
        cli_review, "create_evidence_bundle", lambda *args, **kwargs: tmp_path / "bundle"
    )
    monkeypatch.setattr(cli_review, "save_raw_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "save_summary_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "save_summary_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "save_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "write_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "dump_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "dump_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli_review, "_git_diff", lambda root, git_args: diff_file.read_text(encoding="utf-8")
    )

    args = argparse.Namespace(
        base="", head="HEAD", staged=False, diff_file=[str(diff_file)], diff_stdin=False
    )
    result = cli_review.cmd_review(args)

    out = capsys.readouterr().out
    assert result == 0
    assert "Code review" in out
    assert "task" in captured
    assert "diff_text" in captured
    assert "context" in captured

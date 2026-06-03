from __future__ import annotations

import argparse
from pathlib import Path

from local_codex_lite import cli, cli_query


class _DummyResponse:
    def __init__(self, text: str = "answer") -> None:
        self.text = text
        self.raw = {"model": "qwen25-coder-14b-awq"}


class _DummyClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages, status_label=None, max_tokens=None):
        self.calls.append(messages)
        return _DummyResponse()


def test_ask_rag_includes_retrieved_context(monkeypatch, tmp_path: Path, capsys) -> None:
    captured = {}

    def fake_loader(root, cfg, query):
        return "### local_codex_lite/patcher.py [1-20] (score=3.0; matched: patch)\npatch repair context"

    def fake_client(*args, **kwargs):
        client = _DummyClient()
        captured["client"] = client
        return client

    monkeypatch.setattr(cli_query, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli_query, "_load_rag_context", fake_loader)
    monkeypatch.setattr(cli_query, "OpenAICompatibleClient", fake_client)

    args = argparse.Namespace(evidence_file=[], evidence_stdin=False, rag=True)
    result = cli_query.cmd_ask("how does patch repair work?", args)

    out = capsys.readouterr().out
    assert result == 0
    assert "Retrieved RAG context" in out
    messages = captured["client"].calls[0]
    joined = "\n".join(message["content"] for message in messages)
    assert "patcher.py" in joined
    assert "path:line-range" in joined


def test_preview_rag_passes_retrieved_context_into_prompts(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    captured = {}

    def fake_loader(root, cfg, query):
        return "### local_codex_lite/logging_utils.py [10-20] (score=2.0; matched: logs)\nlogging context"

    def fake_make_plan(task, root, cfg, run_dir=None, extra_context="", runtime_fix=None):
        captured["plan_context"] = extra_context
        captured["runtime_fix"] = runtime_fix
        return {
            "summary": "plan",
            "files_to_inspect": ["local_codex_lite/logging_utils.py"],
            "implementation_steps": ["step"],
            "risks": [],
            "needs_clarification": False,
            "clarifying_questions": [],
        }

    def fake_make_patch(task, plan, root, cfg, run_dir=None, extra_context="", runtime_fix=None):
        captured["patch_context"] = extra_context
        captured["patch_runtime_fix"] = runtime_fix
        return "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"

    monkeypatch.setattr(cli_query, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli_query, "load_config", lambda root: cli.default_config())
    monkeypatch.setattr(cli_query, "_selected_files", lambda root, task, cfg: [])
    monkeypatch.setattr(cli_query, "_load_rag_context", fake_loader)
    monkeypatch.setattr(cli_query, "make_plan", fake_make_plan)
    monkeypatch.setattr(cli_query, "make_patch", fake_make_patch)
    monkeypatch.setattr(cli_query, "preview_patch", lambda root, diff: 0)

    args = argparse.Namespace(
        task="improve logs latest", evidence_file=[], evidence_stdin=False, rag=True
    )
    result = cli_query.cmd_preview(args)

    out = capsys.readouterr().out
    assert result == 0
    assert "Retrieved RAG context" in out
    assert "logging_utils.py" in captured["plan_context"]
    assert "logging_utils.py" in captured["patch_context"]
    assert captured["runtime_fix"] is None
    assert captured["patch_runtime_fix"] is None

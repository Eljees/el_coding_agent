"""More runner control-flow coverage: the clarification gate and the
require-apply safety gate.  Both return before any patch is generated, so they
only need a stub plan (no valid diff) and a throwaway git workspace.
"""

from __future__ import annotations

import argparse
import subprocess
import types
from pathlib import Path

from local_codex_lite import runner
from local_codex_lite.config import AgentConfig


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def _stub_llm(text: str):
    class _LLM:
        def __init__(self, cfg=None):
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            return types.SimpleNamespace(text=text, raw={"model": "stub"})

    return _LLM


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        dry_run=False,
        apply=False,
        execute=False,
        assume_clarification=False,
        evidence_file=[],
        evidence_stdin=False,
        max_patch_attempts=None,
        json_output=False,
        profile=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


_CLARIFY = (
    '{"summary":"s","files_to_inspect":[],"implementation_steps":[],"risks":[],'
    '"needs_clarification":true,"clarifying_questions":["Which file did you mean?"]}'
)
_PLAN = (
    '{"summary":"s","files_to_inspect":["foo.py"],"implementation_steps":[],'
    '"risks":[],"needs_clarification":false,"clarifying_questions":[]}'
)


def test_clarification_without_assume_returns_0(tmp_path, monkeypatch, capsys) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(_CLARIFY))
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    rc = runner.run_task("do something vague", _ns(assume_clarification=False))
    assert rc == 0
    assert "clarif" in capsys.readouterr().out.lower()


def test_require_apply_gate_blocks_without_apply(tmp_path, monkeypatch, capsys) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(_PLAN))
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    rc = runner.run_task("edit foo.py", _ns(apply=False, dry_run=False))
    assert rc == 0
    assert "--apply" in capsys.readouterr().out

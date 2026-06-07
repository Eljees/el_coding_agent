"""More runner control-flow coverage: the clarification gate and the
require-apply safety gate.  Both return before any patch is generated, so they
only need a stub plan (no valid diff) and a throwaway git workspace.
"""

from __future__ import annotations

import argparse
import json
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
        interactive=False,
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


_CLARIFY_NO_QUESTIONS = (
    '{"summary":"s","files_to_inspect":[],"implementation_steps":[],"risks":[],'
    '"needs_clarification":true,"clarifying_questions":[]}'
)


def test_clarification_with_no_questions_still_stops(tmp_path, monkeypatch, capsys) -> None:
    """needs_clarification=true with an empty question list skips the question
    print-out but still stops the run awaiting clarification."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(_CLARIFY_NO_QUESTIONS)
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    rc = runner.run_task("do something vague", _ns(assume_clarification=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Plan needs clarification." not in out
    assert "--assume-clarification" in out


_CLARIFY_TWO = (
    '{"summary":"s","files_to_inspect":[],"implementation_steps":[],"risks":[],'
    '"needs_clarification":true,'
    '"clarifying_questions":["Which file?","Which style?"]}'
)


def test_interactive_clarification_collects_answers_and_revises(
    tmp_path, monkeypatch, capsys
) -> None:
    """--interactive on a TTY: prompt per question, empty answer becomes the
    'use a reasonable default' sentinel, qa_pairs are persisted and the plan is
    revised via revise_plan_with_answers (priority over --assume-clarification)."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(_CLARIFY_TWO))
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: True))
    answers = iter(["foo.py", "   "])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    captured: dict = {}

    def _fake_revise(task, plan, qa_pairs, root, cfg, **kwargs):
        captured["qa_pairs"] = qa_pairs
        return json.loads(_PLAN)

    def _fail_assume(*a, **k):
        raise AssertionError("revise_plan_with_assumptions must not be called in interactive mode")

    monkeypatch.setattr("local_codex_lite.runner.revise_plan_with_answers", _fake_revise)
    monkeypatch.setattr("local_codex_lite.runner.revise_plan_with_assumptions", _fail_assume)

    rc = runner.run_task(
        "do something vague",
        _ns(interactive=True, assume_clarification=True, dry_run=True),
    )

    assert rc == 0
    assert captured["qa_pairs"] == [
        ("Which file?", "foo.py"),
        ("Which style?", "use a reasonable default"),
    ]
    run_dir = next((tmp_path / ".local-codex-lite" / "runs").iterdir())
    saved = json.loads((run_dir / "clarifications.json").read_text(encoding="utf-8"))
    assert saved == [
        {"question": "Which file?", "answer": "foo.py"},
        {"question": "Which style?", "answer": "use a reasonable default"},
    ]
    assert "Revised plan" in capsys.readouterr().out


def test_interactive_without_tty_warns_and_falls_back(tmp_path, monkeypatch, capsys) -> None:
    """--interactive without a TTY: print a warning and keep the current
    behavior (here assume_clarification=False, so the run stops and waits)."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(_CLARIFY))
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: False))

    rc = runner.run_task("do something vague", _ns(interactive=True, assume_clarification=False))

    assert rc == 0
    out = capsys.readouterr().out
    assert "TTY" in out
    assert "--assume-clarification" in out


def test_require_apply_gate_blocks_without_apply(tmp_path, monkeypatch, capsys) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(_PLAN))
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    rc = runner.run_task("edit foo.py", _ns(apply=False, dry_run=False))
    assert rc == 0
    assert "--apply" in capsys.readouterr().out

"""Runner integration: a lesson is recorded only on error-then-success.

Mirrors the stub-LLM + throwaway-git-repo scaffolding of
``test_runner_repair_loop`` but asserts the lessons-memory side effect: the
post-apply syntax gate fails the first patch, the repair succeeds, and exactly
one learned lesson lands in ``.local-codex-lite/lessons.jsonl``.  A clean
first-apply run records nothing.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import subprocess
import types
from pathlib import Path

from local_codex_lite import lessons, runner
from local_codex_lite.config import AgentConfig

_PLAN = (
    '{"summary":"edit foo","files_to_inspect":["foo.py"],'
    '"implementation_steps":[],"risks":[],"needs_clarification":false,'
    '"clarifying_questions":[]}'
)
_DIFF_BROKEN = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1,2 @@\n"
    "+def broken(\n"
    " print('hi')\n"
)
_DIFF_FIX = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1,2 @@\n"
    "+# fixed by repair\n"
    " print('hi')\n"
)
_DIFF_CLEAN = _DIFF_FIX


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def _stub_factory(state: dict, *, first_broken: bool):
    class _LLM:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            joined = " ".join(m.get("content", "") for m in messages).lower()
            if "diff" in joined or "patch" in joined:
                state["diff_calls"] = state.get("diff_calls", 0) + 1
                if first_broken and state["diff_calls"] == 1:
                    text = _DIFF_BROKEN
                else:
                    text = _DIFF_FIX
            elif "command" in joined:
                text = '{"commands": []}'
            else:
                text = _PLAN
            return types.SimpleNamespace(text=text, raw={"model": "stub"})

    return _LLM


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        dry_run=False,
        apply=True,
        execute=False,
        assume_clarification=False,
        evidence_file=[],
        evidence_stdin=False,
        max_patch_attempts=4,
        json_output=False,
        profile=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_lesson_recorded_after_repair_success(tmp_path, monkeypatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient",
        _stub_factory({}, first_broken=True),
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns())

    assert rc == 0
    learned = lessons.load_learned(tmp_path)
    assert len(learned) == 1
    assert learned[0].error_code == "python_syntax_error"
    assert "foo.py" in learned[0].task_excerpt


def test_no_lesson_on_clean_first_apply(tmp_path, monkeypatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient",
        _stub_factory({}, first_broken=False),
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns())

    assert rc == 0
    assert lessons.load_learned(tmp_path) == []

"""Runner failure-path coverage: the patch repair loop, the post-apply Python
syntax gate with backup restore, max_patch_attempts exhaustion, and the
patch-generation exception branch.

These exercise the safety-critical recovery paths in ``runner._run_task_body``
that the happy-path apply test does not reach.  Each test uses a real throwaway
git repo plus a stateful stub LLM (planner builds a fresh client per call, so the
stub shares a counter via a closure dict).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import types
from pathlib import Path

from local_codex_lite import runner
from local_codex_lite.config import AgentConfig

_PLAN = (
    '{"summary":"edit foo","files_to_inspect":["foo.py"],'
    '"implementation_steps":[],"risks":[],"needs_clarification":false,'
    '"clarifying_questions":[]}'
)

# Structurally valid unified diff that applies cleanly but leaves foo.py with a
# Python syntax error (so the post-apply AST gate must trigger a restore).
_DIFF_BROKEN = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1,2 @@\n"
    "+def broken(\n"
    " print('hi')\n"
)
# Valid repair diff applied against the restored original ("print('hi')\n").
_DIFF_FIX = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1,2 @@\n"
    "+# fixed by repair\n"
    " print('hi')\n"
)


def _broken_diff(n: int) -> str:
    """A structurally valid diff that applies but yields invalid Python, made
    distinct per `n` so successive repair attempts are never byte-identical."""
    return (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1,2 @@\n"
        f"+def broken_{n}(\n"
        " print('hi')\n"
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def _stub_factory(state: dict, *, always_broken: bool = False):
    """Build a stub OpenAICompatibleClient class sharing `state` across instances.

    Keys on prompt content exactly like the happy-path test: a diff/patch prompt
    yields a diff, a command prompt yields no commands, anything else is the plan.
    The first diff request returns a broken patch; later ones return the fix
    (unless `always_broken`, used to drive exhaustion).
    """

    class _LLM:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            joined = " ".join(m.get("content", "") for m in messages).lower()
            if "diff" in joined or "patch" in joined:
                state["diff_calls"] = state.get("diff_calls", 0) + 1
                if always_broken:
                    # Distinct broken patch each call: the planner refuses to
                    # return a patch identical to the one that just failed, so
                    # varying the content lets the runner loop reach the
                    # max_patch_attempts ceiling instead of raising early.
                    text = _broken_diff(state["diff_calls"])
                elif state["diff_calls"] == 1:
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
        max_patch_attempts=None,
        json_output=False,
        profile=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _runs(tmp_path: Path) -> list[Path]:
    return list((tmp_path / ".local-codex-lite" / "runs").iterdir())


def test_post_apply_syntax_gate_restores_then_repairs(tmp_path, monkeypatch) -> None:
    """Broken patch applies, fails the AST gate, is restored, and the repair
    attempt succeeds -- run ends OK with patch_attempts == 2."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    state: dict = {}
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient", _stub_factory(state)
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns(max_patch_attempts=4))

    assert rc == 0
    text = (tmp_path / "foo.py").read_text(encoding="utf-8")
    assert "# fixed by repair" in text
    assert "def broken(" not in text  # the broken attempt was rolled back
    result = json.loads((_runs(tmp_path)[0] / "result.json").read_text(encoding="utf-8"))
    assert result["patch_attempts"] == 2
    assert result["applied"] is True


def test_max_patch_attempts_exhausted_returns_1_and_restores(tmp_path, monkeypatch) -> None:
    """Every attempt yields a syntactically broken patch; after the attempt
    budget is spent the run fails and foo.py is left as the pristine original.

    The planner's patch generation and repair are stubbed directly (each returns
    a distinct broken diff) so the test isolates the runner's attempt-budget and
    restore logic rather than the planner's internal repair heuristics.
    """
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    # make_plan still runs through the stub client; make_patch/repair are stubbed.
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient", _stub_factory({})
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr(runner, "make_patch", lambda *a, **k: _broken_diff(1))
    repair_calls = {"n": 1}

    def fake_repair(*a, **k):
        repair_calls["n"] += 1
        return _broken_diff(repair_calls["n"])

    monkeypatch.setattr(runner, "repair_patch_with_error", fake_repair)

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns(max_patch_attempts=2))

    assert rc == 1
    text = (tmp_path / "foo.py").read_text(encoding="utf-8")
    assert text == "print('hi')\n"  # restored, not left broken
    result = json.loads((_runs(tmp_path)[0] / "result.json").read_text(encoding="utf-8"))
    assert result["applied"] is False


def test_patch_generation_exception_returns_1(tmp_path, monkeypatch, capsys) -> None:
    """If patch generation raises, run_task classifies it and exits 1 with a
    failure record rather than propagating the exception."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient", _stub_factory({})
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    def boom(*a, **k):
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(runner, "make_patch", boom)

    rc = runner.run_task("edit foo.py", _ns())
    assert rc == 1
    assert "Patch generation failed" in capsys.readouterr().out
    assert (_runs(tmp_path)[0] / "failure.json").exists()

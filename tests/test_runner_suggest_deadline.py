"""Coverage for the suggest-commands hard deadline.

A loaded vLLM has kept the suggestion stage hanging for ~25 minutes (the
per-request timeout multiplies across client retries and the planner's
context-shrinking attempts).  Suggestions are advisory, so the runner wraps
the call in a wall-clock deadline and skips on any timeout or error instead
of stalling -- the run itself must still succeed.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import time
from pathlib import Path

import pytest

from local_codex_lite import runner
from local_codex_lite.config import AgentConfig

# ---------------------------------------------------------------------------
# _suggest_commands_with_deadline (unit)
# ---------------------------------------------------------------------------


def _call_wrapper(tmp_path: Path, timeout_s: float) -> dict:
    return runner._suggest_commands_with_deadline(
        "task",
        {"summary": "plan"},
        tmp_path,
        AgentConfig(),
        run_dir=tmp_path,
        extra_context="",
        runtime_fix=None,
        timeout_s=timeout_s,
    )


def test_deadline_wrapper_returns_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner, "suggest_commands", lambda *a, **k: {"commands": [{"cmd": "pytest"}]}
    )
    assert _call_wrapper(tmp_path, timeout_s=30) == {"commands": [{"cmd": "pytest"}]}


def test_deadline_wrapper_reraises_worker_exception(tmp_path: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise ValueError("model returned garbage")

    monkeypatch.setattr(runner, "suggest_commands", boom)
    with pytest.raises(ValueError, match="model returned garbage"):
        _call_wrapper(tmp_path, timeout_s=30)


def test_deadline_wrapper_times_out(tmp_path: Path, monkeypatch) -> None:
    def hang(*a, **k):
        time.sleep(5)  # daemon thread: abandoned at deadline, dies with pytest
        return {"commands": []}

    monkeypatch.setattr(runner, "suggest_commands", hang)
    with pytest.raises(TimeoutError, match="deadline"):
        _call_wrapper(tmp_path, timeout_s=0.2)


# ---------------------------------------------------------------------------
# runner integration: skip-and-continue instead of failing the run
# ---------------------------------------------------------------------------

_DIFF = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1,2 @@\n"
    "+# added by agent\n"
    " print('hi')\n"
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        dry_run=False,
        apply=True,
        execute=False,
        smoke=False,
        assume_clarification=False,
        evidence_file=[],
        evidence_stdin=False,
        max_patch_attempts=None,
        json_output=False,
        profile=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_run_continues_when_suggest_commands_fails(tmp_path, monkeypatch) -> None:
    """suggest_commands raising must not fail an otherwise successful apply:
    the runner prints a skip notice, records the reason, and returns 0."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_config", lambda root: AgentConfig())
    monkeypatch.setattr(
        runner, "make_plan", lambda *a, **k: {"summary": "edit foo", "needs_clarification": False}
    )
    monkeypatch.setattr(runner, "make_patch", lambda *a, **k: _DIFF)

    def boom(*a, **k):
        raise RuntimeError("vLLM is busy")

    monkeypatch.setattr(runner, "suggest_commands", boom)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = runner.run_task("add a comment to foo.py", _ns())

    assert rc == 0
    assert "Suggestions skipped" in buffer.getvalue()
    assert "# added by agent" in (tmp_path / "foo.py").read_text(encoding="utf-8")
    run_dir = next(iter((tmp_path / ".local-codex-lite" / "runs").iterdir()))
    commands = json.loads((run_dir / "commands.json").read_text(encoding="utf-8"))
    assert commands == {"commands": []}
    skipped = json.loads((run_dir / "commands_skipped.json").read_text(encoding="utf-8"))
    assert skipped["stage"] == "commands"
    assert "vLLM is busy" in skipped["reason"]
    assert skipped["timeout_seconds"] == 120.0

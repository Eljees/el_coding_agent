"""End-to-end coverage for the runner apply path: plan -> patch -> validate ->
backup -> git apply -> post-apply AST gate -> result.

Uses a real throwaway git repo plus a content-aware stub LLM (returns a plan,
a valid unified diff, or an empty command list depending on the prompt), so the
whole `--apply` flow runs without a live endpoint.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import subprocess
import types
from pathlib import Path

from local_codex_lite import runner
from local_codex_lite.config import AgentConfig

_PLAN = (
    '{"summary":"add a comment","files_to_inspect":["foo.py"],'
    '"implementation_steps":[],"risks":[],"needs_clarification":false,'
    '"clarifying_questions":[]}'
)
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


class _ContentAwareStub:
    def __init__(self, cfg=None) -> None:
        pass

    def chat(self, messages, max_tokens=None, status_label=None):
        joined = " ".join(m.get("content", "") for m in messages).lower()
        if "diff" in joined or "patch" in joined:
            text = _DIFF
        elif "command" in joined:
            text = '{"commands": []}'
        else:
            text = _PLAN
        return types.SimpleNamespace(text=text, raw={"model": "stub"})


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


def test_apply_writes_patch_and_creates_backup(tmp_path, monkeypatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _ContentAwareStub)
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("add a comment to foo.py", _ns())

    assert rc == 0
    assert "# added by agent" in (tmp_path / "foo.py").read_text(encoding="utf-8")
    runs = list((tmp_path / ".local-codex-lite" / "runs").iterdir())
    assert runs, "a run directory should be written"
    assert (runs[0] / "result.json").exists()

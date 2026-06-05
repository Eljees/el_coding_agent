"""Runner coverage: validation-fail loop, apply-fail loop, execute branch,
assume_clarification, evidence_text, and project-workspace-change paths.

Targeted lines in runner._run_task_body:
  105        -- project workspace differs from base (console.print)
  124-125    -- evidence_text saved to bundle
  169-176    -- assume_clarification=True → revise_plan_with_assumptions
  279-340    -- validation-failure loop (non-retryable + retryable-exhausted)
  430-492    -- apply-failure loop (non-retryable + retryable-exhausted + retryable-repair)
  504-521    -- args.execute command-runner branch
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import types
from pathlib import Path

import pytest

from local_codex_lite import runner
from local_codex_lite.config import AgentConfig
from local_codex_lite.patcher import ApplyResult, PatchValidationResult

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_PLAN = (
    '{"summary":"edit foo","files_to_inspect":["foo.py"],'
    '"implementation_steps":[],"risks":[],"needs_clarification":false,'
    '"clarifying_questions":[]}'
)
_PLAN_CLARIFY = (
    '{"summary":"edit foo","files_to_inspect":["foo.py"],'
    '"implementation_steps":[],"risks":[],"needs_clarification":true,'
    '"clarifying_questions":["Which style guide?"]}'
)
_DIFF = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1 +1,2 @@\n"
    "+# added\n"
    " print('hi')\n"
)
_CMDS_JSON = '{"commands": [{"cmd": "python foo.py", "purpose": "smoke test"}]}'


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def _stub_llm(plan_text=_PLAN, diff_text=_DIFF, cmd_text=_CMDS_JSON):
    """Content-aware LLM stub: dispatches on keywords in the prompt."""

    class _LLM:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            joined = " ".join(m.get("content", "") for m in messages).lower()
            if "diff" in joined or "patch" in joined:
                text = diff_text
            elif "command" in joined:
                text = cmd_text
            else:
                text = plan_text
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


def _ok_val():
    return PatchValidationResult(ok=True, errors=[])


# ---------------------------------------------------------------------------
# Validation-failure paths (lines 279-340)
# ---------------------------------------------------------------------------


def test_validation_failure_nonretryable_returns_1(tmp_path, monkeypatch, capsys) -> None:
    """unsafe_path validation error is not retryable → return 1 immediately, write failure.json."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr("local_codex_lite.runner.make_patch", lambda *a, **k: _DIFF)
    monkeypatch.setattr(
        "local_codex_lite.runner.validate_diff",
        lambda *a, **k: PatchValidationResult(
            ok=False, errors=["sensitive path blocked: /etc/passwd"]
        ),
    )

    rc = runner.run_task("edit foo.py", _ns())

    assert rc == 1
    run_dir = _runs(tmp_path)[0]
    assert (run_dir / "failure.json").exists()
    failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "validation"


def test_validation_failure_retryable_exhausted_returns_1(tmp_path, monkeypatch) -> None:
    """Retryable validation failure (malformed_diff) exhausts max_patch_attempts → return 1."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    call_n = {"n": 0}

    def _always_bad_patch(*a, **k):
        call_n["n"] += 1
        return _DIFF

    monkeypatch.setattr("local_codex_lite.runner.make_patch", _always_bad_patch)
    monkeypatch.setattr("local_codex_lite.runner.repair_patch_with_error", _always_bad_patch)
    monkeypatch.setattr(
        "local_codex_lite.runner.validate_diff",
        lambda *a, **k: PatchValidationResult(
            ok=False, errors=["invalid unified diff: no hunks found"]
        ),
    )

    with io.StringIO() as _sink:
        rc = runner.run_task("edit foo.py", _ns(max_patch_attempts=2))

    assert rc == 1
    # make_patch once + repair once = 2 calls total
    assert call_n["n"] == 2


# ---------------------------------------------------------------------------
# Apply-failure paths (lines 430-492)
# ---------------------------------------------------------------------------


def _bad_apply(stderr: str, returncode: int = 1) -> ApplyResult:
    return ApplyResult(returncode=returncode, stdout="", stderr=stderr, strategy="git apply")


def test_apply_failure_nonretryable_returns_1(tmp_path, monkeypatch) -> None:
    """'outside workspace' apply error is not retryable → return 1, no repair attempt."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr("local_codex_lite.runner.make_patch", lambda *a, **k: _DIFF)
    monkeypatch.setattr("local_codex_lite.runner.validate_diff", lambda *a, **k: _ok_val())
    monkeypatch.setattr("local_codex_lite.runner.backup_paths", lambda *a, **k: None)
    monkeypatch.setattr(
        "local_codex_lite.runner.apply_patch",
        lambda *a, **k: _bad_apply("outside workspace: /etc/passwd"),
    )
    repair_calls = {"n": 0}
    monkeypatch.setattr(
        "local_codex_lite.runner.repair_patch_with_error",
        lambda *a, **k: repair_calls.update({"n": repair_calls["n"] + 1}) or _DIFF,
    )

    rc = runner.run_task("edit foo.py", _ns())

    assert rc == 1
    assert repair_calls["n"] == 0, "non-retryable error must not trigger repair"
    run_dir = _runs(tmp_path)[0]
    assert (run_dir / "failure.json").exists()
    failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "apply"


def test_apply_failure_retryable_then_success(tmp_path, monkeypatch) -> None:
    """Context-mismatch apply fails once (retryable), then succeeds on repair attempt."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    apply_calls = {"n": 0}

    def _apply_once_then_ok(*a, **k):
        apply_calls["n"] += 1
        if apply_calls["n"] == 1:
            return _bad_apply("patch does not apply")
        # Second call applies the real diff via the original function.
        from local_codex_lite.patcher import apply_patch as _real

        return _real(*a, **k)

    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr("local_codex_lite.runner.make_patch", lambda *a, **k: _DIFF)
    monkeypatch.setattr("local_codex_lite.runner.validate_diff", lambda *a, **k: _ok_val())
    monkeypatch.setattr("local_codex_lite.runner.backup_paths", lambda *a, **k: None)
    monkeypatch.setattr("local_codex_lite.runner.apply_patch", _apply_once_then_ok)
    monkeypatch.setattr("local_codex_lite.runner.repair_patch_with_error", lambda *a, **k: _DIFF)

    with io.StringIO() as _sink:
        rc = runner.run_task("edit foo.py", _ns(max_patch_attempts=3))

    assert rc == 0
    assert apply_calls["n"] == 2


def test_apply_failure_retryable_exhausted_returns_nonzero(tmp_path, monkeypatch) -> None:
    """Retryable apply failure persists until max_patch_attempts → return non-zero."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    monkeypatch.setattr("local_codex_lite.runner.make_patch", lambda *a, **k: _DIFF)
    monkeypatch.setattr("local_codex_lite.runner.validate_diff", lambda *a, **k: _ok_val())
    monkeypatch.setattr("local_codex_lite.runner.backup_paths", lambda *a, **k: None)
    monkeypatch.setattr(
        "local_codex_lite.runner.apply_patch",
        lambda *a, **k: _bad_apply("hunk #1 FAILED at 1"),
    )
    repair_calls = {"n": 0}

    def _repair(*a, **k):
        repair_calls["n"] += 1
        return _DIFF

    monkeypatch.setattr("local_codex_lite.runner.repair_patch_with_error", _repair)

    rc = runner.run_task("edit foo.py", _ns(max_patch_attempts=2))

    assert rc != 0
    # With max_patch_attempts=2: attempt 1 fails → repair → attempt 2 fails → exhausted
    assert repair_calls["n"] == 1
    run_dir = _runs(tmp_path)[0]
    assert (run_dir / "failure.json").exists()


# ---------------------------------------------------------------------------
# Execute branch (lines 504-521)
# ---------------------------------------------------------------------------


def test_execute_branch_runs_suggested_commands(tmp_path, monkeypatch) -> None:
    """When --exec is set, suggested commands are executed and outputs logged."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    exec_calls = []

    def _fake_run_command(cmd, cwd=None, timeout=None):
        exec_calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("local_codex_lite.runner.run_command", _fake_run_command)

    with io.StringIO() as _sink:
        rc = runner.run_task("add a comment to foo.py", _ns(apply=True, execute=True))

    assert rc == 0
    assert exec_calls, "run_command should have been called for the suggested command"
    run_dir = _runs(tmp_path)[0]
    assert (run_dir / "test_outputs.json").exists()


def test_execute_branch_handles_blocked_command(tmp_path, monkeypatch) -> None:
    """If run_command raises ValueError (blocked), output records returncode 126."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    def _blocked(cmd, cwd=None, timeout=None):
        raise ValueError("dangerous command blocked")

    monkeypatch.setattr("local_codex_lite.runner.run_command", _blocked)

    with io.StringIO() as _sink:
        rc = runner.run_task("add a comment to foo.py", _ns(apply=True, execute=True))

    assert rc == 0
    run_dir = _runs(tmp_path)[0]
    outputs = json.loads((run_dir / "test_outputs.json").read_text(encoding="utf-8"))
    assert any(o["returncode"] == 126 for o in outputs)


# ---------------------------------------------------------------------------
# assume_clarification branch (lines 169-176)
# ---------------------------------------------------------------------------


def test_assume_clarification_continues_after_revision(tmp_path, monkeypatch) -> None:
    """When needs_clarification=True and assume_clarification=True, plan is revised
    and the run continues (here stopped at dry_run=True for minimal stubbing)."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "local_codex_lite.planner.OpenAICompatibleClient", _stub_llm(plan_text=_PLAN_CLARIFY)
    )
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())
    revised_called = {"called": False}

    def _fake_revise(*a, **k):
        revised_called["called"] = True
        # Return a valid plan JSON so the runner can continue.
        return json.loads(_PLAN)

    monkeypatch.setattr("local_codex_lite.runner.revise_plan_with_assumptions", _fake_revise)

    rc = runner.run_task("do something vague", _ns(assume_clarification=True, dry_run=True))

    assert rc == 0
    assert revised_called["called"], "revise_plan_with_assumptions must be called"


# ---------------------------------------------------------------------------
# Evidence text branch (lines 124-125)
# ---------------------------------------------------------------------------


def test_evidence_file_is_saved_to_bundle(tmp_path, monkeypatch) -> None:
    """When evidence_file is provided, evidence_text is non-empty and persisted."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    evidence = tmp_path / "trace.txt"
    evidence.write_text(
        "Traceback (most recent call last):\n  ...\nValueError: bad", encoding="utf-8"
    )

    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    rc = runner.run_task("fix the error", _ns(apply=False, evidence_file=[str(evidence)]))

    assert rc == 0
    run_dir = _runs(tmp_path)[0]
    # The user_evidence.txt should be written to the run directory.
    assert (run_dir / "user_evidence.txt").exists() or any(
        f.name.endswith("user_evidence.txt") for f in run_dir.rglob("*")
    )


# ---------------------------------------------------------------------------
# Project workspace change branch (line 105)
# ---------------------------------------------------------------------------


def test_project_workspace_change_is_announced(tmp_path, monkeypatch, capsys) -> None:
    """When resolve_task_workspace returns a different root than CWD, the change is printed."""
    _init_git_repo(tmp_path)
    new_ws = tmp_path / "generated_projects" / "calc"
    new_ws.mkdir(parents=True)
    # Initialise git in the generated workspace too (needed for apply path).
    subprocess.run(["git", "-C", str(new_ws), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(new_ws), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(new_ws), "config", "user.name", "t"], check=True)
    (new_ws / "main.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(new_ws), "add", "main.py"], check=True)
    subprocess.run(["git", "-C", str(new_ws), "commit", "-qm", "init"], check=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.runner.resolve_task_workspace", lambda base, task: new_ws)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _stub_llm())
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    # dry_run so we exit before apply (no patch needed).
    rc = runner.run_task("создай новый калькулятор", _ns(apply=False, dry_run=True))

    assert rc == 0
    out = capsys.readouterr().out
    assert "Project workspace" in out

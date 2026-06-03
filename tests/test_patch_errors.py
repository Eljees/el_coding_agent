from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from local_codex_lite import cli, runner
from local_codex_lite.config import AgentConfig
from local_codex_lite.patch_errors import classify_patch_apply, classify_patch_validation
from local_codex_lite.prompts import patch_repair_prompt_for_issue


def test_classifies_malformed_diff() -> None:
    error = classify_patch_apply("error: corrupt patch at line 12")

    assert error.code == "malformed_diff"
    assert error.retryable is True


def test_classifies_context_mismatch() -> None:
    error = classify_patch_apply(
        "error: patch failed: app.py:10\nerror: app.py: patch does not apply"
    )

    assert error.code == "context_mismatch"
    assert error.retryable is True


def test_classifies_file_already_exists() -> None:
    error = classify_patch_apply("error: foo.py: already exists in working directory")

    assert error.code == "file_already_exists"
    assert error.retryable is True


def test_classifies_path_mismatch() -> None:
    error = classify_patch_validation(["outside workspace: ../foo.py"])

    assert error.code == "path_mismatch"
    assert error.retryable is True


def test_classifies_unsafe_path_as_not_retryable() -> None:
    error = classify_patch_validation(["sensitive path blocked: .env"])

    assert error.code == "unsafe_path"
    assert error.retryable is False


def test_unknown_fallback_is_retryable() -> None:
    error = classify_patch_apply("some unexpected git apply failure")

    assert error.code == "unknown"
    assert error.retryable is True


def test_repair_prompt_includes_error_class() -> None:
    messages = patch_repair_prompt_for_issue(
        "context_mismatch",
        "fix app",
        '{"summary": "fix"}',
        "diff --git a/app.py b/app.py",
        "patch does not apply",
        "# Tree\napp.py",
    )

    content = "\n".join(message["content"] for message in messages)
    assert "Issue type: context_mismatch" in content
    assert "current workspace context" in content


def test_new_file_already_exists_idempotency_is_not_broken(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "foo.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_config", lambda root: AgentConfig())
    monkeypatch.setattr(
        runner,
        "make_plan",
        lambda *args, **kwargs: {"summary": "create foo", "needs_clarification": False},
    )
    monkeypatch.setattr(
        runner,
        "make_patch",
        lambda *args, **kwargs: "\n".join(
            [
                "diff --git a/foo.py b/foo.py",
                "new file mode 100644",
                "--- /dev/null",
                "+++ b/foo.py",
                "@@ -0,0 +1,1 @@",
                "+print('ok')",
            ]
        ),
    )
    monkeypatch.setattr(runner, "suggest_commands", lambda *args, **kwargs: {"commands": []})
    monkeypatch.setattr(runner, "backup_paths", lambda *args, **kwargs: tmp_path / "backup")
    monkeypatch.setattr(
        runner,
        "apply_patch",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["git", "apply"],
            returncode=1,
            stdout="",
            stderr="error: foo.py: already exists in working directory",
        ),
    )

    result = cli._run_task(
        "create foo.py",
        argparse.Namespace(dry_run=False, apply=True, execute=False, assume_clarification=False),
    )

    assert result == 0

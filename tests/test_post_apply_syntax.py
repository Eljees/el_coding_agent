"""Tests for the post-apply AST validator that rejects syntactically broken
Python patches.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from local_codex_lite.patcher import (
    SyntaxIssue,
    backup_paths,
    restore_from_run_backups,
    validate_python_syntax,
)
from local_codex_lite.patch_errors import classify_python_syntax_error


# ---------------------------------------------------------------------------
# validate_python_syntax
# ---------------------------------------------------------------------------

def test_validate_python_syntax_accepts_clean_file(tmp_path: Path) -> None:
    p = tmp_path / "ok.py"
    p.write_text("x = 1\nprint(x)\n", encoding="utf-8")
    assert validate_python_syntax([p]) == []


def test_validate_python_syntax_reports_broken_file(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("def f(:\n    pass\n", encoding="utf-8")
    issues = validate_python_syntax([p])
    assert len(issues) == 1
    assert issues[0].path == p
    # ast.SyntaxError gives a line number; we only assert the shape so the
    # exact CPython wording change doesn't snap the test.
    assert "line" in issues[0].detail


def test_validate_python_syntax_skips_non_python(tmp_path: Path) -> None:
    txt = tmp_path / "notes.md"
    txt.write_text("def f(:", encoding="utf-8")  # would be a syntax error if .py
    assert validate_python_syntax([txt]) == []


def test_validate_python_syntax_skips_missing_files(tmp_path: Path) -> None:
    assert validate_python_syntax([tmp_path / "does-not-exist.py"]) == []


def test_validate_python_syntax_reports_each_broken_file(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("def a(:\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("ok = True\n", encoding="utf-8")
    c = tmp_path / "c.py"
    c.write_text("class C:\n    1 +\n", encoding="utf-8")
    issues = validate_python_syntax([a, b, c])
    paths = sorted(str(issue.path) for issue in issues)
    assert paths == [str(a), str(c)]


# ---------------------------------------------------------------------------
# restore_from_run_backups (companion to validate_python_syntax)
# ---------------------------------------------------------------------------

def test_restore_from_run_backups_round_trip(tmp_path: Path) -> None:
    """backup_paths writes <run_dir>/backups/<rel>; restore_from_run_backups
    copies them back over the workspace.  Together they round-trip cleanly."""
    workspace = tmp_path
    target = workspace / "pkg" / "foo.py"
    target.parent.mkdir(parents=True)
    target.write_text("original = True\n", encoding="utf-8")

    run_dir = workspace / ".local-codex-lite" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    backup_paths([target], workspace, run_dir=run_dir)

    # Simulate a bad patch that left the file in a broken state.
    target.write_text("WAS_PATCHED = invalid syntax (\n", encoding="utf-8")

    restored = restore_from_run_backups([target], workspace, run_dir)
    assert restored == 1
    assert target.read_text() == "original = True\n"


def test_restore_from_run_backups_skips_missing(tmp_path: Path) -> None:
    """If a touched file has no backup (newly created by the patch), restore
    silently skips it and reports a count of 0.  The caller decides how to
    proceed; we don't second-guess by deleting brand-new files."""
    workspace = tmp_path
    run_dir = workspace / ".local-codex-lite" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    new_file = workspace / "brand_new.py"
    new_file.write_text("x = 1\n", encoding="utf-8")
    assert restore_from_run_backups([new_file], workspace, run_dir) == 0
    # The file is left as is.
    assert new_file.read_text() == "x = 1\n"


# ---------------------------------------------------------------------------
# classify_python_syntax_error
# ---------------------------------------------------------------------------

def test_classify_python_syntax_error_is_retryable() -> None:
    err = classify_python_syntax_error("foo.py: line 12: invalid syntax")
    assert err.code == "python_syntax_error"
    assert err.retryable is True
    assert "line 12" in err.detail
    # Suggested action mentions the model: this is what the user sees in
    # the run dir's failure.json when retries are exhausted.
    assert "model" in err.suggested_action.lower()

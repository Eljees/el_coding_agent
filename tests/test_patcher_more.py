"""Additional coverage for patcher.py — edge cases not hit by existing tests.

Covers: detect_runtime_fix_context branches, validate_diff guards,
backup_paths legacy path, apply_patch nested-repo logic,
_diff_paths_already_prefixed, _discover_git_root, validate_python_syntax
OSError, restore_from_run_backups outside-workspace ValueError.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_codex_lite.patcher import (
    _diff_paths_already_prefixed,
    _discover_git_root,
    apply_patch,
    backup_paths,
    detect_runtime_fix_context,
    restore_from_run_backups,
    validate_diff,
    validate_python_syntax,
)

# ---------------------------------------------------------------------------
# detect_runtime_fix_context — uncovered branches
# ---------------------------------------------------------------------------


def test_detect_returns_none_when_no_traceback_keyword(tmp_path: Path) -> None:
    ctx = detect_runtime_fix_context("fix", "Some log output without the keyword.", tmp_path)
    assert ctx is None


def test_detect_filters_out_non_python_paths(tmp_path: Path) -> None:
    py_file = tmp_path / "good.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    evidence = (
        "Traceback (most recent call last):\n"
        f'  File "{tmp_path / "ignored.txt"}", line 1, in <module>\n'
        f'  File "{py_file}", line 1, in <module>\n'
        "ValueError: boom\n"
    )
    ctx = detect_runtime_fix_context("fix", evidence, tmp_path)
    assert ctx is not None
    assert ctx.target_path == py_file.resolve()


def test_detect_skips_oserror_on_path_resolve(tmp_path: Path) -> None:
    ok_file = tmp_path / "ok.py"
    ok_file.write_text("x = 1\n", encoding="utf-8")
    bad_path = tmp_path / "bad.py"
    evidence = (
        "Traceback (most recent call last):\n"
        f'  File "{bad_path}", line 1, in <module>\n'
        f'  File "{ok_file}", line 1, in <module>\n'
        "ValueError: boom\n"
    )
    original_resolve = Path.resolve

    def selective_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self.name == "bad.py":
            raise OSError("Cannot resolve path")
        return original_resolve(self, *args, **kwargs)

    with patch.object(Path, "resolve", selective_resolve):
        ctx = detect_runtime_fix_context("fix", evidence, tmp_path)

    assert ctx is not None
    assert ctx.target_path.name == "ok.py"


def test_detect_skips_duplicate_path(tmp_path: Path) -> None:
    py_file = tmp_path / "dup.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    evidence = (
        "Traceback (most recent call last):\n"
        f'  File "{py_file}", line 1, in fn1\n'
        f'  File "{py_file}", line 2, in fn2\n'
        "RuntimeError: dup\n"
    )
    ctx = detect_runtime_fix_context("fix", evidence, tmp_path)
    assert ctx is not None
    assert ctx.secondary_files == ()


def test_detect_secondary_oserror_skips_that_file(tmp_path: Path) -> None:
    primary = tmp_path / "primary.py"
    secondary = tmp_path / "secondary.py"
    primary.write_text("primary code\n", encoding="utf-8")
    secondary.write_text("secondary code\n", encoding="utf-8")
    evidence = (
        "Traceback (most recent call last):\n"
        f'  File "{primary}", line 1, in fn\n'
        f'  File "{secondary}", line 1, in fn\n'
        "RuntimeError: err\n"
    )

    original_read = Path.read_text

    def selective_oserror(self: Path, **kwargs: object) -> str:
        if self.name == "secondary.py":
            raise OSError("Permission denied")
        return original_read(self, **kwargs)

    with patch.object(Path, "read_text", selective_oserror):
        ctx = detect_runtime_fix_context("fix", evidence, tmp_path)
    assert ctx is not None
    assert ctx.target_path.name == "primary.py"
    assert ctx.secondary_files == ()


# ---------------------------------------------------------------------------
# validate_diff — uncovered guards
# ---------------------------------------------------------------------------


def test_validate_diff_rejects_empty_diff(tmp_path: Path) -> None:
    result = validate_diff("   \n\t  ", tmp_path)
    assert not result.ok
    assert "empty diff" in result.errors


def test_validate_diff_skips_dev_null_path(tmp_path: Path) -> None:
    (tmp_path / "newfile.py").write_text("x = 1\n", encoding="utf-8")
    diff = "\n".join(
        [
            "--- a//dev/null",
            "+++ b/newfile.py",
            "@@ -0,0 +1 @@",
            "+x = 1",
        ]
    )
    result = validate_diff(diff, tmp_path)
    assert result.ok


def test_validate_diff_rejects_path_outside_workspace(tmp_path: Path) -> None:
    diff = "\n".join(
        [
            "--- a/../../../etc/passwd",
            "+++ b/../../../etc/passwd",
            "@@ -1 +1 @@",
            "-root:x:0",
            "+root:x:1",
        ]
    )
    result = validate_diff(diff, tmp_path)
    assert not result.ok
    assert any("outside workspace" in e for e in result.errors)


def test_validate_diff_rejects_sensitive_path(tmp_path: Path) -> None:
    diff = "\n".join(
        [
            "--- a/.env",
            "+++ b/.env",
            "@@ -1 +1 @@",
            "-SECRET=old",
            "+SECRET=new",
        ]
    )
    result = validate_diff(diff, tmp_path)
    assert not result.ok
    assert any("sensitive" in e for e in result.errors)


def test_validate_diff_sensitive_path_allowed_with_flag(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=x\n", encoding="utf-8")
    diff = "\n".join(
        [
            "--- a/.env",
            "+++ b/.env",
            "@@ -1 +1 @@",
            "-SECRET=old",
            "+SECRET=new",
        ]
    )
    result = validate_diff(diff, tmp_path, allow_sensitive_read=True)
    assert result.ok


def test_validate_diff_rejects_diff_with_no_file_paths(tmp_path: Path) -> None:
    diff = "@@ -1,2 +1,2 @@\n-old line\n+new line\n"
    result = validate_diff(diff, tmp_path)
    assert not result.ok
    assert "no file paths found" in result.errors


# ---------------------------------------------------------------------------
# backup_paths — legacy path (no run_dir)
# ---------------------------------------------------------------------------


def test_backup_paths_uses_legacy_location_when_no_run_dir(tmp_path: Path) -> None:
    src = tmp_path / "src.py"
    src.write_text("x = 1\n", encoding="utf-8")

    backup_root = backup_paths([src], tmp_path)

    expected = tmp_path / ".local-codex-lite" / "backups" / "current"
    assert backup_root == expected
    assert (backup_root / "src.py").read_text() == "x = 1\n"


def test_backup_paths_skips_nonexistent_file(tmp_path: Path) -> None:
    ghost = tmp_path / "ghost.py"
    backup_root = backup_paths([ghost], tmp_path, run_dir=None)
    assert not (backup_root / "ghost.py").exists()


# ---------------------------------------------------------------------------
# _diff_paths_already_prefixed
# ---------------------------------------------------------------------------


def test_diff_paths_prefixed_returns_false_for_empty_rel_dir() -> None:
    assert _diff_paths_already_prefixed("--- a/foo.py\n+++ b/foo.py\n", "") is False


def test_diff_paths_prefixed_skips_dev_null_returns_false() -> None:
    diff = "--- a//dev/null\n+++ b//dev/null\n"
    assert _diff_paths_already_prefixed(diff, "subdir") is False


def test_diff_paths_prefixed_detects_prefix() -> None:
    diff = "--- a/subdir/foo.py\n+++ b/subdir/foo.py\n"
    assert _diff_paths_already_prefixed(diff, "subdir") is True


def test_diff_paths_prefixed_returns_false_when_no_match() -> None:
    diff = "--- a/other/foo.py\n+++ b/other/foo.py\n"
    assert _diff_paths_already_prefixed(diff, "subdir") is False


# ---------------------------------------------------------------------------
# _discover_git_root — non-git directory
# ---------------------------------------------------------------------------


def test_discover_git_root_returns_none_when_git_fails(tmp_path: Path) -> None:
    import subprocess as _subprocess

    def fake_run(cmd: list[str], **kwargs: object) -> _subprocess.CompletedProcess[str]:
        return _subprocess.CompletedProcess(cmd, returncode=128, stdout="", stderr="not a git repo")

    with patch("local_codex_lite.patcher.subprocess.run", side_effect=fake_run):
        result = _discover_git_root(tmp_path)

    assert result is None


# ---------------------------------------------------------------------------
# apply_patch — uncovered paths
# ---------------------------------------------------------------------------


def test_apply_patch_raises_when_no_git_repo(tmp_path: Path) -> None:
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    with patch("local_codex_lite.patcher._discover_git_root", return_value=None):
        with pytest.raises(RuntimeError, match="git repo required"):
            apply_patch(diff, tmp_path, run_dir=None)


def test_apply_patch_uses_legacy_patch_file_when_no_run_dir(tmp_path: Path) -> None:
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("local_codex_lite.patcher._discover_git_root", return_value=tmp_path):
        with patch("local_codex_lite.patcher.subprocess.run", return_value=mock_result):
            apply_patch(diff, tmp_path, run_dir=None)

    legacy_patch = tmp_path / ".local-codex-lite" / "patch.diff"
    assert legacy_patch.exists()
    assert legacy_patch.read_text(encoding="utf-8") == diff


def test_apply_patch_nested_repo_directory_prefix_strategy(tmp_path: Path) -> None:
    git_root = tmp_path / "repo"
    workspace = git_root / "subproject"
    workspace.mkdir(parents=True)
    run_dir = workspace / ".run"
    run_dir.mkdir()
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("local_codex_lite.patcher._discover_git_root", return_value=git_root):
        with patch("local_codex_lite.patcher.subprocess.run", return_value=mock_result):
            result = apply_patch(diff, workspace, run_dir=run_dir)

    assert result.strategy == "directory_prefix"
    assert result.returncode == 0


def test_apply_patch_nested_repo_in_diff_prefix_strategy(tmp_path: Path) -> None:
    git_root = tmp_path / "repo"
    workspace = git_root / "subproject"
    workspace.mkdir(parents=True)
    run_dir = workspace / ".run"
    run_dir.mkdir()
    rel = "subproject"
    diff = f"--- a/{rel}/f.py\n+++ b/{rel}/f.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("local_codex_lite.patcher._discover_git_root", return_value=git_root):
        with patch("local_codex_lite.patcher.subprocess.run", return_value=mock_result):
            result = apply_patch(diff, workspace, run_dir=run_dir)

    assert result.strategy == "in_diff_prefix"


def test_apply_patch_nested_repo_workspace_not_relative_to_git_root(tmp_path: Path) -> None:
    git_root = tmp_path / "other_repo"
    git_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_dir = workspace / ".run"
    run_dir.mkdir()
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    mock_result = MagicMock(returncode=0, stdout="", stderr="")

    with patch("local_codex_lite.patcher._discover_git_root", return_value=git_root):
        with patch("local_codex_lite.patcher.subprocess.run", return_value=mock_result):
            result = apply_patch(diff, workspace, run_dir=run_dir)

    assert result.strategy == "git_root_relative"


# ---------------------------------------------------------------------------
# validate_python_syntax — OSError / UnicodeDecodeError on read
# ---------------------------------------------------------------------------


def test_validate_python_syntax_skips_oserror_on_read(tmp_path: Path) -> None:
    p = tmp_path / "locked.py"
    p.write_text("x = 1\n", encoding="utf-8")

    original_read = Path.read_text

    def raise_oserror(self: Path, **kwargs: object) -> str:
        if self.name == "locked.py":
            raise OSError("Permission denied")
        return original_read(self, **kwargs)

    with patch.object(Path, "read_text", raise_oserror):
        issues = validate_python_syntax([p])

    assert issues == []


def test_validate_python_syntax_skips_unicode_decode_error(tmp_path: Path) -> None:
    p = tmp_path / "binary.py"
    p.write_bytes(b"\xff\xfe invalid utf-8")

    issues = validate_python_syntax([p])
    assert issues == []


# ---------------------------------------------------------------------------
# restore_from_run_backups — path outside workspace (ValueError)
# ---------------------------------------------------------------------------


def test_restore_from_run_backups_skips_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_dir = workspace / ".run"
    run_dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("data\n", encoding="utf-8")

    restored = restore_from_run_backups([outside], workspace, run_dir)

    assert restored == 0
    assert outside.read_text() == "data\n"

from __future__ import annotations

from pathlib import Path

from local_codex_lite.patcher import validate_diff


def test_validate_diff_rejects_noop_diff(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("print('x')\n", encoding="utf-8")
    diff = "\n".join(
        [
            "diff --git a/foo.py b/foo.py",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -1 +1 @@",
            "-print('x')",
            "+print('x')",
        ]
    )

    result = validate_diff(diff, tmp_path)

    assert not result.ok
    assert "no-op diff" in result.errors


def test_validate_diff_rejects_comment_only_diff(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("for row in range(3):\n    pass\n", encoding="utf-8")
    diff = "\n".join(
        [
            "diff --git a/foo.py b/foo.py",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -1,2 +1,2 @@",
            "-for row in range(3):",
            "+for row in range(3):  # comment only",
            "-    pass",
            "+    pass",
        ]
    )

    result = validate_diff(diff, tmp_path)

    assert not result.ok
    assert "no-op diff" in result.errors

"""Tests for the multi-file runtime-fix context (RuntimeFixContext.secondary_files).

The agent stays single-file for the *patch*: only ``target_path`` is
modified.  ``secondary_files`` is read-only context so the model can
reason about the call chain when a traceback spans several modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_codex_lite.patcher import RuntimeFixContext, detect_runtime_fix_context
from local_codex_lite.prompts import (
    _runtime_fix_related_block,
    runtime_fix_single_file_patch_prompt,
    runtime_fix_single_file_plan_prompt,
)


def _traceback(*paths: Path) -> str:
    """Build a Python traceback whose frames point at the given paths in
    order.  Newest-frame-first, matching CPython's default format."""
    lines = ["Traceback (most recent call last):"]
    for i, path in enumerate(paths):
        lines.append(f'  File "{path}", line {i + 1}, in fn{i}')
        lines.append(f"    raise ValueError({i!r})")
    lines.append("ValueError: 0")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# detect_runtime_fix_context: secondary_files population
# ---------------------------------------------------------------------------


def test_detect_returns_secondary_files_for_multifile_traceback(tmp_path: Path) -> None:
    ws = tmp_path.resolve()
    (ws / "pkg").mkdir()
    (ws / "pkg" / "a.py").write_text("def a(): raise ValueError(0)\n", encoding="utf-8")
    (ws / "pkg" / "b.py").write_text("from pkg.a import a\n\ndef b():\n    a()\n", encoding="utf-8")
    (ws / "pkg" / "c.py").write_text("from pkg.b import b\n\ndef c():\n    b()\n", encoding="utf-8")

    ctx = detect_runtime_fix_context(
        "fix the bug",
        _traceback(ws / "pkg" / "c.py", ws / "pkg" / "b.py", ws / "pkg" / "a.py"),
        ws,
    )
    assert ctx is not None
    assert ctx.target_path.name == "c.py"
    names = [p.name for p, _ in ctx.secondary_files]
    assert names == ["b.py", "a.py"]
    # Content is read from disk, not from the traceback text.
    contents = {p.name: text for p, text in ctx.secondary_files}
    assert "from pkg.a import a" in contents["b.py"]
    assert "raise ValueError(0)" in contents["a.py"]


def test_detect_caps_secondary_files_at_two(tmp_path: Path) -> None:
    """Even if the traceback names 4 in-workspace files, we keep only the
    primary plus 2 secondaries to control prompt size."""
    ws = tmp_path.resolve()
    names = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    for n in names:
        (ws / n).write_text(f"# {n}\n", encoding="utf-8")
    paths = [ws / n for n in names]

    ctx = detect_runtime_fix_context("fix", _traceback(*paths), ws)
    assert ctx is not None
    assert ctx.target_path.name == "a.py"
    assert len(ctx.secondary_files) == 2
    assert [p.name for p, _ in ctx.secondary_files] == ["b.py", "c.py"]


def test_detect_skips_files_outside_workspace(tmp_path: Path) -> None:
    """A traceback frame outside the workspace must not contribute to
    secondary_files."""
    ws = tmp_path.resolve()
    (ws / "in.py").write_text("# in\n", encoding="utf-8")
    outside = tmp_path.parent / "totally-outside.py"
    ctx = detect_runtime_fix_context(
        "fix",
        _traceback(ws / "in.py", outside),
        ws,
    )
    assert ctx is not None
    assert ctx.secondary_files == ()


def test_detect_returns_empty_secondary_files_for_single_frame(tmp_path: Path) -> None:
    ws = tmp_path.resolve()
    (ws / "only.py").write_text("raise ValueError(0)\n", encoding="utf-8")
    ctx = detect_runtime_fix_context("fix", _traceback(ws / "only.py"), ws)
    assert ctx is not None
    assert ctx.target_path.name == "only.py"
    assert ctx.secondary_files == ()


# ---------------------------------------------------------------------------
# _runtime_fix_related_block: prompt rendering
# ---------------------------------------------------------------------------


def test_related_block_empty_returns_empty_string() -> None:
    assert _runtime_fix_related_block(()) == ""
    assert _runtime_fix_related_block([]) == ""


def test_related_block_emits_one_section_per_file() -> None:
    block = _runtime_fix_related_block(
        [
            ("pkg/a.py", "def a(): pass\n"),
            ("pkg/b.py", "def b(): pass\n"),
        ]
    )
    assert "Related files" in block
    assert "do NOT patch" in block
    assert "--- pkg/a.py ---" in block
    assert "--- pkg/b.py ---" in block


def test_related_block_truncates_long_content() -> None:
    body = "x = 1\n" * 1000  # ~6 KB
    block = _runtime_fix_related_block([("big.py", body)])
    assert "truncated" in block
    # Block size is bounded by ~2 KB per file plus header.
    assert len(block) < 3000


# ---------------------------------------------------------------------------
# Prompt functions accept related_files without breaking existing call sites
# ---------------------------------------------------------------------------


def test_plan_prompt_includes_related_block_when_present() -> None:
    msgs = runtime_fix_single_file_plan_prompt(
        "fix",
        "pkg/a.py",
        "Traceback...\nValueError: 0",
        "def a(): pass\n",
        related_files=(("pkg/b.py", "def b(): pass\n"),),
    )
    content = "\n".join(m["content"] for m in msgs)
    assert "Related files" in content
    assert "pkg/b.py" in content


def test_plan_prompt_omits_related_block_when_empty() -> None:
    """Backward compatibility: existing callers that don't pass
    related_files must produce the same prompt shape as before."""
    msgs = runtime_fix_single_file_plan_prompt(
        "fix",
        "pkg/a.py",
        "Traceback...",
        "def a(): pass\n",
    )
    content = "\n".join(m["content"] for m in msgs)
    assert "Related files" not in content


def test_patch_prompt_includes_related_block_when_present() -> None:
    msgs = runtime_fix_single_file_patch_prompt(
        "fix",
        '{"summary": "x"}',
        "pkg/a.py",
        "Traceback...\nValueError: 0",
        "def a(): pass\n",
        related_files=(("pkg/b.py", "def b(): pass\n"),),
    )
    content = "\n".join(m["content"] for m in msgs)
    assert "Related files" in content
    assert "pkg/b.py" in content

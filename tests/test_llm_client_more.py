"""Additional coverage for llm_client.py — extract_json/diff edge cases,
normalize_unified_diff special lines, _emit_status."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from local_codex_lite.config import default_config
from local_codex_lite.llm_client import (
    OpenAICompatibleClient,
    _drop_leading_blank_lines,
    extract_diff,
    extract_json,
    normalize_unified_diff,
)

# ---------------------------------------------------------------------------
# extract_json — empty text raises (line 118)
# ---------------------------------------------------------------------------


def test_extract_json_raises_on_empty_text() -> None:
    with pytest.raises(ValueError, match="empty text"):
        extract_json("")


def test_extract_json_raises_on_whitespace_text() -> None:
    with pytest.raises(ValueError, match="empty text"):
        extract_json("   \n  ")


# ---------------------------------------------------------------------------
# extract_diff — empty text raises (line 166)
# ---------------------------------------------------------------------------


def test_extract_diff_raises_on_empty_text() -> None:
    with pytest.raises(ValueError, match="empty text"):
        extract_diff("")


def test_extract_diff_raises_on_whitespace_text() -> None:
    with pytest.raises(ValueError, match="empty text"):
        extract_diff("   \n\n")


# ---------------------------------------------------------------------------
# _drop_leading_blank_lines — strips leading blank lines (line 194)
# ---------------------------------------------------------------------------


def test_drop_leading_blank_lines_removes_leading_blanks() -> None:
    text = "\n\n  \nactual content\nnext line"
    result = _drop_leading_blank_lines(text)
    assert result.startswith("actual content")


def test_drop_leading_blank_lines_no_leading_blanks() -> None:
    text = "first line\nsecond line"
    assert _drop_leading_blank_lines(text) == text


# ---------------------------------------------------------------------------
# normalize_unified_diff — invalid hunk header (line 216)
# ---------------------------------------------------------------------------


def test_normalize_unified_diff_raises_on_invalid_hunk_header() -> None:
    diff = "--- a/foo.py\n+++ b/foo.py\n@@ invalid hunk header @@\n+x = 1\n"
    with pytest.raises(ValueError, match="Invalid unified diff hunk header"):
        normalize_unified_diff(diff)


# ---------------------------------------------------------------------------
# normalize_unified_diff — next section header breaks body loop (line 223)
# ---------------------------------------------------------------------------


def test_normalize_unified_diff_handles_consecutive_hunk_starts() -> None:
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "@@ -5,1 +5,1 @@\n"
        "+new\n"
    )
    result = normalize_unified_diff(diff)
    # Two separate @@ hunks should appear in the normalized output
    assert result.count("@@ ") == 2


# ---------------------------------------------------------------------------
# normalize_unified_diff — no-newline marker is preserved (lines 233-234)
# ---------------------------------------------------------------------------


def test_normalize_unified_diff_preserves_no_newline_marker() -> None:
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old_line\n"
        "\\ No newline at end of file\n"
        "+new_line\n"
    )
    result = normalize_unified_diff(diff)
    assert "\\ No newline at end of file" in result


# ---------------------------------------------------------------------------
# normalize_unified_diff — empty body line becomes context line (lines 242-245)
# ---------------------------------------------------------------------------


def test_normalize_unified_diff_empty_body_line_becomes_context() -> None:
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " first\n"
        "\n"
        " third\n"
    )
    result = normalize_unified_diff(diff)
    lines = result.splitlines()
    body_lines = [ln for ln in lines if ln.startswith(" ") or ln == " "]
    assert any(ln == " " for ln in body_lines)


# ---------------------------------------------------------------------------
# normalize_unified_diff — closing fence inside hunk ends body (line 248)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# OpenAICompatibleClient._emit_status — writes to stderr (line 101)
# ---------------------------------------------------------------------------


def test_emit_status_writes_to_stderr() -> None:
    client = OpenAICompatibleClient(default_config().llm)
    fake_stderr = MagicMock()
    with patch("local_codex_lite.llm_client.sys.stderr", fake_stderr):
        client._emit_status("test message")
    fake_stderr.write.assert_called_once_with("test message\n")
    fake_stderr.flush.assert_called_once()


def test_normalize_unified_diff_stops_at_closing_fence() -> None:
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "+new line\n"
        "```\n"
        "some trailing text\n"
    )
    result = normalize_unified_diff(diff)
    assert "trailing text" not in result

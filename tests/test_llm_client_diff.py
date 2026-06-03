"""Edge-case and property-based tests for the diff handling in llm_client.

`extract_diff` is the first line of defense against malformed LLM output:
it strips prose, finds fenced blocks, and hands off to
`normalize_unified_diff`, which rewrites hunk headers so they match the
actual `+`/`-`/` ` line counts inside the hunk.  Together they decide
whether `git apply` will be invoked on the model's reply at all.

These tests bracket both: hand-rolled edge cases plus a hypothesis-based
property pass when the optional dependency is available.
"""

from __future__ import annotations

import pytest

from local_codex_lite.llm_client import extract_diff, normalize_unified_diff

SIMPLE_DIFF = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"


# ---------------------------------------------------------------------------
# extract_diff: shaping the raw LLM reply into a usable diff
# ---------------------------------------------------------------------------


def test_extract_diff_plain_input() -> None:
    out = extract_diff(SIMPLE_DIFF)
    assert "diff --git a/foo.py b/foo.py" in out
    assert "+new" in out


def test_extract_diff_with_fenced_diff_block() -> None:
    raw = "Here is the patch:\n```diff\n" + SIMPLE_DIFF + "```\n"
    out = extract_diff(raw)
    assert out.startswith("diff --git ")
    assert "+new" in out


def test_extract_diff_with_unlabeled_fence() -> None:
    raw = "OK:\n```\n" + SIMPLE_DIFF + "```\n"
    assert "diff --git" in extract_diff(raw)


def test_extract_diff_strips_preamble_without_fence() -> None:
    raw = "Some prose first.\n\n" + SIMPLE_DIFF
    out = extract_diff(raw)
    assert out.startswith("diff --git ")


def test_extract_diff_rejects_empty_response() -> None:
    with pytest.raises(ValueError):
        extract_diff("")


def test_extract_diff_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError):
        extract_diff("   \n  \n")


def test_extract_diff_rejects_pure_prose() -> None:
    with pytest.raises(ValueError):
        extract_diff("I cannot generate a diff because there is nothing to change.")


def test_extract_diff_handles_unterminated_fence() -> None:
    """Some small local models emit ```diff\\n<content> without ever closing
    the fence.  extract_diff must still pull the diff out instead of
    rejecting the response."""
    raw = "```diff\n" + SIMPLE_DIFF
    out = extract_diff(raw)
    assert "diff --git" in out
    assert "+new" in out


def test_extract_diff_drops_leading_blank_lines_inside_fence() -> None:
    raw = "```diff\n\n\n" + SIMPLE_DIFF + "```\n"
    out = extract_diff(raw)
    assert out.startswith("diff --git ")


# ---------------------------------------------------------------------------
# normalize_unified_diff: rewriting hunk headers
# ---------------------------------------------------------------------------


def test_normalize_idempotent_on_simple_diff() -> None:
    once = normalize_unified_diff(SIMPLE_DIFF)
    twice = normalize_unified_diff(once)
    assert once == twice


def test_normalize_recomputes_wrong_hunk_counts() -> None:
    """If the model emits a hunk header that disagrees with the body,
    normalize must rewrite the header to match the body."""
    bad = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,5 +1,5 @@\n"  # claims 5/5 but body is 1/1
        "-old\n"
        "+new\n"
    )
    out = normalize_unified_diff(bad)
    assert "@@ -1 +1 @@" in out


def test_normalize_promotes_empty_context_line_to_single_space() -> None:
    """A bare empty line inside a hunk encodes an empty source line.
    Many JSON / pretty-printer transports strip the leading space; the
    canonical encoding is a single space, and normalize must restore it
    so ``git apply`` accepts the hunk."""
    raw = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " a\n"
        "\n"  # bare empty - context for an empty source line
        "-b\n"
        "+c\n"
    )
    out = normalize_unified_diff(raw)
    assert " a\n \n-b\n+c" in out


def test_normalize_preserves_no_newline_marker() -> None:
    raw = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "\\ No newline at end of file\n"
    )
    out = normalize_unified_diff(raw)
    assert "\\ No newline at end of file" in out


def test_normalize_rejects_malformed_hunk_header() -> None:
    bad = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ this is not a header @@\n"
        "-old\n"
        "+new\n"
    )
    with pytest.raises(ValueError):
        normalize_unified_diff(bad)


def test_normalize_rejects_unexpected_line_prefix() -> None:
    bad = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "?not-a-context-line\n"
    )
    with pytest.raises(ValueError):
        normalize_unified_diff(bad)


def test_normalize_handles_two_hunks() -> None:
    raw = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "@@ -10 +10 @@\n"
        "-c\n"
        "+d\n"
    )
    out = normalize_unified_diff(raw)
    assert out.count("@@") >= 4  # two opening + two closing markers
    assert "+b" in out and "+d" in out


# ---------------------------------------------------------------------------
# Hypothesis property tests (skipped when hypothesis is not installed)
# ---------------------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is optional")
from hypothesis import given, settings
from hypothesis import strategies as st


def _format_range(start: int, count: int) -> str:
    return f"{start}" if count == 1 else f"{start},{count}"


@settings(max_examples=80, deadline=None)
@given(
    ctx=st.integers(min_value=0, max_value=6),
    removed=st.integers(min_value=0, max_value=6),
    added=st.integers(min_value=0, max_value=6),
)
def test_normalize_recomputes_header_from_body_property(
    ctx: int,
    removed: int,
    added: int,
) -> None:
    """For any (context, removed, added) combination, normalize must rewrite
    the hunk header so it matches the body, regardless of what the model
    originally claimed in the header."""
    if ctx + removed + added == 0:
        return  # an empty hunk is rejected by validate_diff anyway
    body_lines: list[str] = []
    for i in range(ctx):
        body_lines.append(f" ctx{i}")
    for i in range(removed):
        body_lines.append(f"-rm{i}")
    for i in range(added):
        body_lines.append(f"+ad{i}")
    raw = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,99 +1,99 @@\n" + "\n".join(body_lines) + "\n"  # intentionally wrong counts
    )
    out = normalize_unified_diff(raw)
    # Header should now reflect the actual body counts.
    expected_old = ctx + removed
    expected_new = ctx + added
    expected_header = f"@@ -{_format_range(1, expected_old)} +{_format_range(1, expected_new)} @@"
    assert expected_header in out
    # And normalize is idempotent.
    assert normalize_unified_diff(out) == out


@settings(max_examples=40, deadline=None)
@given(prose_len=st.integers(min_value=0, max_value=200))
def test_extract_diff_strips_preamble_property(prose_len: int) -> None:
    """No matter how much prose the model puts before the actual diff,
    extract_diff still surfaces the diff intact."""
    preamble = "x " * prose_len
    out = extract_diff(preamble + "\n\n" + SIMPLE_DIFF)
    assert out.startswith("diff --git ")
    assert "+new" in out

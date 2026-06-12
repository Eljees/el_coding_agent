"""Additional coverage for patch_errors.py — uncovered classify branches
and _short_detail edge cases."""

from __future__ import annotations

import pytest

from local_codex_lite.patch_errors import (
    classify_patch_apply,
    classify_patch_validation,
    classify_post_apply_runtime,
)

# ---------------------------------------------------------------------------
# classify_patch_validation — unknown fallthrough (line 88)
# ---------------------------------------------------------------------------


def test_classify_patch_validation_unknown_fallthrough() -> None:
    result = classify_patch_validation("some unrecognized validation error text")
    assert result.code == "unknown"


# ---------------------------------------------------------------------------
# classify_patch_apply — path_mismatch for "no such file" (line 103)
# ---------------------------------------------------------------------------


def test_classify_patch_apply_path_mismatch_no_such_file() -> None:
    result = classify_patch_apply("error: no such file foo.py")
    assert result.code == "path_mismatch"


def test_classify_patch_apply_path_mismatch_pathspec() -> None:
    result = classify_patch_apply("pathspec 'bar.py' did not match any files")
    assert result.code == "path_mismatch"


def test_classify_patch_apply_path_mismatch_unrecognized_input() -> None:
    result = classify_patch_apply("unrecognized input")
    assert result.code == "path_mismatch"


# ---------------------------------------------------------------------------
# _short_detail — empty input returns default message (line 123)
# ---------------------------------------------------------------------------


def test_classify_patch_apply_empty_stderr_returns_unknown() -> None:
    result = classify_patch_apply("", "")
    assert result.code == "unknown"


def test_classify_patch_validation_empty_list_returns_no_details() -> None:
    result = classify_patch_validation([])
    assert result.code == "unknown"
    assert result.detail == "No details were provided."


# ---------------------------------------------------------------------------
# _short_detail — long input is truncated (line 126)
# ---------------------------------------------------------------------------


def test_classify_patch_apply_long_error_is_truncated() -> None:
    long_stderr = "patch does not apply: " + "x" * 600
    result = classify_patch_apply(long_stderr)
    assert result.code == "context_mismatch"
    assert len(result.detail) <= 500
    assert result.detail.endswith("...")


# ---------------------------------------------------------------------------
# classify_post_apply_runtime — smoke test
# ---------------------------------------------------------------------------


def test_classify_post_apply_runtime_returns_classification() -> None:
    result = classify_post_apply_runtime("Traceback (most recent call last):\n  ...\nValueError: bad")
    assert result.code is not None
    assert result.title

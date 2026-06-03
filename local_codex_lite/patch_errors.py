from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PatchErrorCode = Literal[
    "malformed_diff",
    "context_mismatch",
    "file_already_exists",
    "path_mismatch",
    "unsafe_path",
    "empty_patch",
    "python_syntax_error",
    "unknown",
]


@dataclass(frozen=True)
class PatchErrorClassification:
    code: PatchErrorCode
    title: str
    detail: str
    retryable: bool
    suggested_action: str


_PATCH_ERROR_DETAILS: dict[PatchErrorCode, tuple[str, bool, str]] = {
    "malformed_diff": (
        "Malformed diff",
        True,
        "Ask the model for a syntactically valid unified diff with correct hunk headers.",
    ),
    "context_mismatch": (
        "Patch context mismatch",
        True,
        "Regenerate the diff against the current file contents.",
    ),
    "file_already_exists": (
        "File already exists",
        True,
        "Keep idempotent success when safe, otherwise ask for an update-existing-file diff.",
    ),
    "path_mismatch": (
        "Patch path mismatch",
        True,
        "Repair paths to use repo-relative workspace paths only.",
    ),
    "unsafe_path": (
        "Unsafe path blocked",
        False,
        "Fail closed; do not ask the model to repair unsafe or sensitive paths.",
    ),
    "empty_patch": (
        "Empty patch",
        True,
        "Ask for a non-empty patch or treat the task as a no-op without applying changes.",
    ),
    "python_syntax_error": (
        "Python syntax error after apply",
        True,
        "Ask the model for a corrected diff that produces syntactically valid Python.",
    ),
    "unknown": (
        "Unknown patch error",
        True,
        "Use the generic patch repair prompt and keep evidence in logs.",
    ),
}


def classify_patch_validation(errors: list[str]) -> PatchErrorClassification:
    text = " ".join(errors)
    lower = text.lower()
    if "sensitive path blocked" in lower:
        return _classification("unsafe_path", text)
    if "outside workspace" in lower:
        return _classification("path_mismatch", text)
    if "empty diff" in lower or "no-op diff" in lower:
        return _classification("empty_patch", text)
    if "no file paths found" in lower or "invalid unified diff" in lower:
        return _classification("malformed_diff", text)
    return _classification("unknown", text)


def classify_patch_apply(stderr: str, stdout: str = "") -> PatchErrorClassification:
    raw = (stderr or stdout or "").strip()
    lower = raw.lower()
    if "already exists in working directory" in lower:
        return _classification("file_already_exists", raw)
    if "patch does not apply" in lower or ("hunk" in lower and "failed" in lower):
        return _classification("context_mismatch", raw)
    if "corrupt patch" in lower or "invalid unified diff" in lower:
        return _classification("malformed_diff", raw)
    if "outside workspace" in lower or "path traversal" in lower:
        return _classification("unsafe_path", raw)
    if "no such file" in lower or "pathspec" in lower or "unrecognized input" in lower:
        return _classification("path_mismatch", raw)
    if not lower:
        return _classification("unknown", "git apply failed without stderr")
    return _classification("unknown", raw)


def _classification(code: PatchErrorCode, raw_detail: str) -> PatchErrorClassification:
    title, retryable, suggested_action = _PATCH_ERROR_DETAILS[code]
    return PatchErrorClassification(
        code=code,
        title=title,
        detail=_short_detail(raw_detail),
        retryable=retryable,
        suggested_action=suggested_action,
    )


def _short_detail(value: str, limit: int = 500) -> str:
    compact = " ".join(value.replace("\r", "\n").split())
    if not compact:
        return "No details were provided."
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def classify_python_syntax_error(detail: str) -> PatchErrorClassification:
    """Build a PatchErrorClassification for a post-apply Python syntax
    failure.  Kept separate from the diff/apply classifiers because it
    is triggered by a different check (ast.parse on the resulting file
    content, not git apply stderr)."""
    return _classification("python_syntax_error", detail)

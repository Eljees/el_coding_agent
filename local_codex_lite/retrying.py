from __future__ import annotations

from typing import Literal

import httpx

RetryIssue = Literal[
    "malformed_diff",
    "context_too_large",
    "file_already_exists",
    "path_mismatch",
    "endpoint_unavailable",
    "unknown",
]


def classify_httpx_exception(exc: Exception) -> RetryIssue:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = (getattr(exc.response, "text", "") or "").lower()
        if status in {400, 413} and any(
            marker in body
            for marker in (
                "context too large",
                "maximum context length",
                "too large",
                "exceeds",
            )
        ):
            return "context_too_large"
        if status >= 500:
            return "endpoint_unavailable"
        return "unknown"
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        ),
    ):
        return "endpoint_unavailable"
    return "unknown"


def strategy_for_issue(issue: RetryIssue) -> str:
    return {
        "malformed_diff": "repair_diff",
        "context_too_large": "reduce_context",
        "file_already_exists": "accept_existing_file",
        "path_mismatch": "repair_paths",
        "endpoint_unavailable": "retry_endpoint",
        "unknown": "generic_retry",
    }[issue]

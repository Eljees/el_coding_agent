from __future__ import annotations

import httpx

from local_codex_lite.patch_errors import classify_patch_apply, classify_patch_validation
from local_codex_lite.retrying import (
    classify_httpx_exception,
    strategy_for_issue,
)


def test_classify_httpx_exception_context_too_large() -> None:
    request = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
    response = httpx.Response(
        400, request=request, text="This model's maximum context length is 6000 tokens."
    )
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)

    assert classify_httpx_exception(exc) == "context_too_large"
    assert strategy_for_issue("context_too_large") == "reduce_context"


def test_classify_httpx_exception_endpoint_unavailable() -> None:
    request = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
    exc = httpx.ConnectError("connection refused", request=request)

    assert classify_httpx_exception(exc) == "endpoint_unavailable"
    assert strategy_for_issue("endpoint_unavailable") == "retry_endpoint"


def test_classify_patch_validation_errors_path_mismatch() -> None:
    result = classify_patch_validation(["outside workspace: ../etc/passwd"])
    assert result.code == "path_mismatch"
    assert strategy_for_issue("path_mismatch") == "repair_paths"


def test_classify_apply_error_file_already_exists() -> None:
    result = classify_patch_apply("error: file already exists in working directory")
    assert result.code == "file_already_exists"
    assert strategy_for_issue("file_already_exists") == "accept_existing_file"


def test_classify_httpx_exception_server_error() -> None:
    request = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("service unavailable", request=request, response=response)

    assert classify_httpx_exception(exc) == "endpoint_unavailable"


def test_classify_httpx_exception_unknown_client_error() -> None:
    request = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
    response = httpx.Response(400, request=request, text='{"error": "bad request"}')
    exc = httpx.HTTPStatusError("bad request", request=request, response=response)

    assert classify_httpx_exception(exc) == "unknown"

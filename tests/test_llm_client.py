import threading
from unittest.mock import MagicMock

import pytest

from local_codex_lite.config import LLMConfig
from local_codex_lite.llm_client import (
    LLMResponse,
    OpenAICompatibleClient,
    extract_diff,
    extract_json,
    normalize_unified_diff,
    repair_json_response,
)


def test_extract_json_from_fenced_block() -> None:
    text = """```json
    {"a": 1}
    ```"""
    assert extract_json(text) == {"a": 1}


def test_extract_diff_from_fenced_block() -> None:
    text = """```diff
    diff --git a/foo.py b/foo.py
    --- a/foo.py
    +++ b/foo.py
    @@ -1 +1 @@
    -print("hi")
    +print("bye")
    ```"""
    diff = extract_diff(text)
    assert "diff --git a/foo.py b/foo.py" in diff
    assert 'print("bye")' in diff


def test_normalize_unified_diff_fixes_hunk_sizes() -> None:
    text = "\n".join(
        [
            "diff --git a/foo.py b/foo.py",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -0,0 +1,235 @@",
            '+print("hello")',
            '+print("world")',
        ]
    )
    normalized = normalize_unified_diff(text)
    assert "@@ -0,0 +1,2 @@" in normalized
    assert normalized.endswith("\n")


def test_emit_status_ignores_broken_stderr(monkeypatch) -> None:
    client = OpenAICompatibleClient(LLMConfig())

    class BrokenStderr:
        def write(self, text):
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr("sys.stderr", BrokenStderr())

    client._emit_status("hello")


# ---------------------------------------------------------------------------
# OpenAICompatibleClient.chat — happy path and retry logic
# ---------------------------------------------------------------------------


def _make_fake_response(text: str = "pong") -> MagicMock:
    """Return a mock httpx Response with the minimal interface that
    ``OpenAICompatibleClient._request_with_heartbeat`` calls."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    return resp


def test_chat_succeeds_on_first_attempt(monkeypatch) -> None:
    import httpx

    client = OpenAICompatibleClient(LLMConfig(retries=0))

    def fake_post(self, url, *, json=None):
        return _make_fake_response("hello")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    resp = client.chat([{"role": "user", "content": "ping"}])
    assert resp.text == "hello"
    assert "choices" in resp.raw


def test_chat_retries_on_transient_error(monkeypatch) -> None:
    import httpx

    client = OpenAICompatibleClient(LLMConfig(retries=2, timeout=5.0))
    call_count = 0

    def flaky_post(self, url, *, json=None):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.ConnectError("connection refused")
        return _make_fake_response("recovered")

    monkeypatch.setattr(httpx.Client, "post", flaky_post)
    monkeypatch.setattr("time.sleep", lambda _: None)  # skip back-off sleep

    resp = client.chat([{"role": "user", "content": "hello"}])
    assert resp.text == "recovered"
    assert call_count == 2


def test_chat_raises_after_exhausting_retries(monkeypatch) -> None:
    import httpx

    client = OpenAICompatibleClient(LLMConfig(retries=1, timeout=5.0))

    def always_fail(self, url, *, json=None):
        raise httpx.ConnectError("always down")

    monkeypatch.setattr(httpx.Client, "post", always_fail)
    monkeypatch.setattr("time.sleep", lambda _: None)

    with pytest.raises(httpx.ConnectError):
        client.chat([{"role": "user", "content": "ping"}])


def test_chat_with_status_label_emits_heartbeat(monkeypatch) -> None:
    """status_label path: heartbeat thread is started but does not block completion."""
    import httpx

    client = OpenAICompatibleClient(LLMConfig(retries=0))
    emitted: list[str] = []

    def fake_post(self, url, *, json=None):
        return _make_fake_response("ok")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(
        client,
        "_emit_status",
        lambda msg: emitted.append(msg),  # type: ignore[attr-defined]
    )

    resp = client.chat([{"role": "user", "content": "hi"}], status_label="test-op")
    assert resp.text == "ok"
    # At minimum the initial "test-op..." message and the "done" message.
    assert any("test-op" in m for m in emitted)


def test_heartbeat_loop_exits_when_stopped() -> None:
    """_heartbeat_loop must exit promptly once stop_event is set."""
    client = OpenAICompatibleClient(LLMConfig())
    stop = threading.Event()
    emitted: list[str] = []

    def capture_emit(msg: str) -> None:
        emitted.append(msg)

    client._emit_status = capture_emit  # type: ignore[method-assign]

    # Set the stop event immediately so the loop body never runs.
    stop.set()
    client._heartbeat_loop(stop, "noop-label")
    # Loop exited without emitting anything (stop_event was already set).
    assert emitted == []


def test_healthcheck_returns_text_and_raw(monkeypatch) -> None:
    import httpx

    client = OpenAICompatibleClient(LLMConfig(retries=0))

    def fake_post(self, url, *, json=None):
        return _make_fake_response("pong")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = client.healthcheck()
    assert result["text"] == "pong"
    assert "choices" in result["raw"]


# ---------------------------------------------------------------------------
# repair_json_response
# ---------------------------------------------------------------------------


def test_repair_json_response_uses_chat_and_extracts_json(monkeypatch) -> None:
    class FakeClient:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text='{"fixed": true}', raw={})

    result = repair_json_response(
        FakeClient(),
        original_messages=[{"role": "user", "content": "q"}],
        bad_text="not json",
        max_tokens=512,
    )
    assert result == {"fixed": True}

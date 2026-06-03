"""Planner can be driven with an injected LLM client (the SupportsChat seam).

Before this seam the only way to exercise make_plan/make_patch/make_review in a
test was to monkeypatch ``planner.OpenAICompatibleClient``.  Now a conforming
double can be passed in directly, so the planner's parse/return logic is unit
testable without touching module globals or the network.
"""

from __future__ import annotations

import pytest

from local_codex_lite import planner
from local_codex_lite.config import AgentConfig
from local_codex_lite.llm_client import LLMResponse, SupportsChat

_REVIEW_JSON = (
    '{"summary": "ok", "overall_risk": "low", "findings": [], '
    '"positives": [], "missing_context": [], "recommendation": "approve"}'
)


class _FakeClient:
    """Records calls and returns a canned payload; never hits the network."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[tuple[object, object, object]] = []

    def chat(self, messages, max_tokens=None, status_label=None) -> LLMResponse:
        self.calls.append((messages, max_tokens, status_label))
        return LLMResponse(text=self.payload, raw={"model": "fake"})


def test_fake_client_satisfies_supports_chat() -> None:
    assert isinstance(_FakeClient("{}"), SupportsChat)


def test_make_review_uses_injected_client(tmp_path) -> None:
    fake = _FakeClient(_REVIEW_JSON)
    result = planner.make_review(
        "review the diff", "diff --git a/x b/x", tmp_path, AgentConfig(), client=fake
    )
    assert result["recommendation"] == "approve"
    assert fake.calls, "the injected client.chat must be used"


def test_make_plan_uses_injected_client(tmp_path) -> None:
    fake = _FakeClient('{"steps": ["do x"], "files": ["a.py"]}')
    result = planner.make_plan("do x", tmp_path, AgentConfig(), client=fake)
    assert result["steps"] == ["do x"]
    assert fake.calls


def test_injection_skips_real_client_construction(tmp_path, monkeypatch) -> None:
    # If the seam works, the real client is never constructed even when the
    # network/endpoint is unavailable.
    def _boom(*args, **kwargs):
        raise AssertionError("OpenAICompatibleClient must not be constructed when client= is given")

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _boom)
    fake = _FakeClient(_REVIEW_JSON)
    result = planner.make_review("t", "diff", tmp_path, AgentConfig(), client=fake)
    assert result["recommendation"] == "approve"

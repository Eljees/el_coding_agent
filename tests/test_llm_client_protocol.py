"""Contract test for the LLM client seam (local_codex_lite.llm_client.SupportsChat).

This locks down the single structural interface the planner/runner reach the
model through, so test doubles and the real client cannot silently drift apart.
"""

from __future__ import annotations

from local_codex_lite.config import LLMConfig
from local_codex_lite.llm_client import LLMResponse, OpenAICompatibleClient, SupportsChat


def test_real_client_satisfies_protocol() -> None:
    client = OpenAICompatibleClient(LLMConfig())
    assert isinstance(client, SupportsChat)


def test_minimal_double_satisfies_protocol() -> None:
    class FakeClient:
        def chat(self, messages, max_tokens=None, status_label=None) -> LLMResponse:
            return LLMResponse(text="{}", raw={})

    assert isinstance(FakeClient(), SupportsChat)


def test_object_without_chat_does_not_satisfy_protocol() -> None:
    class NotAClient:
        pass

    assert not isinstance(NotAClient(), SupportsChat)

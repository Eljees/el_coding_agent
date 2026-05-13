from __future__ import annotations

from dataclasses import dataclass

from local_codex_lite.config import LLMConfig
from local_codex_lite.doctor import build_doctor_probe_client, probe_local_llm_health
from local_codex_lite.llm_client import LLMResponse


@dataclass
class FakeClient:
    response: LLMResponse

    def chat(self, messages, max_tokens=None):  # noqa: ANN001
        return self.response


def test_probe_local_llm_health_accepts_strict_json() -> None:
    client = FakeClient(
        response=LLMResponse(
            text='{"ok": true, "component": "doctor"}',
            raw={"model": "qwen25-coder-14b-awq"},
        )
    )
    probe = probe_local_llm_health(client, "qwen25-coder-14b-awq")
    assert probe.endpoint_ok is True
    assert probe.json_ok is True
    assert probe.model_ok is True
    assert probe.json_error is None


def test_probe_local_llm_health_accepts_fenced_json() -> None:
    client = FakeClient(
        response=LLMResponse(
            text='Here you go:\n```json\n{"ok": true, "component": "doctor"}\n```',
            raw={"model": "qwen25-coder-14b-awq"},
        )
    )
    probe = probe_local_llm_health(client, "qwen25-coder-14b-awq")
    assert probe.endpoint_ok is True
    assert probe.json_ok is True


def test_probe_local_llm_health_reports_malformed_json() -> None:
    client = FakeClient(
        response=LLMResponse(
            text="not json",
            raw={"model": "qwen25-coder-14b-awq"},
        )
    )
    probe = probe_local_llm_health(client, "qwen25-coder-14b-awq")
    assert probe.endpoint_ok is True
    assert probe.json_ok is False
    assert probe.json_error is not None


def test_probe_local_llm_health_reports_endpoint_failure() -> None:
    class BrokenClient:
        def chat(self, messages, max_tokens=None):  # noqa: ANN001
            raise RuntimeError("connection refused")

    probe = probe_local_llm_health(BrokenClient(), "qwen25-coder-14b-awq")
    assert probe.endpoint_ok is False
    assert probe.error == "connection refused"


def test_build_doctor_probe_client_uses_short_timeout_without_retries() -> None:
    config = LLMConfig(timeout=120.0, retries=3)

    client = build_doctor_probe_client(config)

    assert client.config.timeout == 10.0
    assert client.config.retries == 0
    assert client.config.base_url == config.base_url
    assert client.config.model == config.model

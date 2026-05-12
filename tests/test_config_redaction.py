from __future__ import annotations

from local_codex_lite.config import _redact_sensitive_structure


def test_nested_sensitive_redaction_handles_dicts_lists_and_tuples() -> None:
    payload = {
        "llm": {
            "api_key": "secret-api-key",
            "nested": [
                {"token": "token-value"},
                ("keep", {"private_key": "ssh-key"}),
            ],
        },
        "meta": {
            "items": [
                {"credential": "cred"},
                {"access_key": "access"},
                {"git_pass": "git-pass"},
            ]
        },
        "safe": "value",
    }

    redacted = _redact_sensitive_structure(payload)

    assert redacted["llm"]["api_key"] == "<redacted>"
    assert redacted["llm"]["nested"][0]["token"] == "<redacted>"
    assert redacted["llm"]["nested"][1][1]["private_key"] == "<redacted>"
    assert redacted["meta"]["items"][0]["credential"] == "<redacted>"
    assert redacted["meta"]["items"][1]["access_key"] == "<redacted>"
    assert redacted["meta"]["items"][2]["git_pass"] == "<redacted>"
    assert redacted["safe"] == "value"

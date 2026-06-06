from __future__ import annotations

from local_codex_lite.cli import _normalize_suggested_commands


def test_normalize_suggested_commands_filters_prose_steps() -> None:
    payload = {
        "commands": [
            {"cmd": "Create a new Python file named 'calculator.py'.", "reason": "x", "risk": "y"},
            {"cmd": "python generated_projects/demo.py", "reason": "run demo", "risk": "low"},
        ]
    }

    normalized = _normalize_suggested_commands(payload)

    assert normalized == {
        "commands": [
            {"cmd": "python generated_projects/demo.py", "reason": "run demo", "risk": "low"}
        ]
    }


def test_normalize_suggested_commands_accepts_bare_list_payload() -> None:
    # The LLM frequently returns the list without the {"commands": ...}
    # envelope; this used to crash the --apply path with AttributeError.
    payload = [
        {"cmd": "pytest tests/", "reason": "verify", "risk": "low"},
        "python demo.py",
        {"not_cmd": "garbage"},
    ]

    normalized = _normalize_suggested_commands(payload)

    assert normalized == {
        "commands": [
            {"cmd": "pytest tests/", "reason": "verify", "risk": "low"},
            {"cmd": "python demo.py", "reason": "", "risk": ""},
        ]
    }


def test_normalize_suggested_commands_rejects_non_dict_non_list() -> None:
    assert _normalize_suggested_commands("run pytest") == {"commands": []}
    assert _normalize_suggested_commands(None) == {"commands": []}


def test_normalize_suggested_commands_filters_unix_only_commands() -> None:
    payload = {
        "commands": [
            {"cmd": "sed -i 's/a/b/' demo.py", "reason": "edit", "risk": "medium"},
            {"cmd": "pytest tests/test_demo.py", "reason": "run tests", "risk": "low"},
        ]
    }

    normalized = _normalize_suggested_commands(payload)

    assert normalized == {
        "commands": [{"cmd": "pytest tests/test_demo.py", "reason": "run tests", "risk": "low"}]
    }


def test_normalize_suggested_commands_filters_editor_commands() -> None:
    payload = {
        "commands": [
            {"cmd": "notepad.exe demo.py", "reason": "open editor", "risk": "low"},
            {"cmd": "python demo.py", "reason": "run demo", "risk": "low"},
        ]
    }

    normalized = _normalize_suggested_commands(payload)

    assert normalized == {
        "commands": [{"cmd": "python demo.py", "reason": "run demo", "risk": "low"}]
    }

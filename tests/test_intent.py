"""Tests for local_codex_lite.intent."""
from __future__ import annotations

import pytest

from local_codex_lite.capabilities import default_capabilities
from local_codex_lite.intent import (
    IntentDecision,
    decision_as_dict,
    extract_artifact_input_path,
    extract_artifact_output_path,
    recognize_intent,
)


CAPS = default_capabilities()


# ---------------------------------------------------------------------------
# recognize_intent
# ---------------------------------------------------------------------------

def test_recognize_intent_empty_text_returns_needs_input() -> None:
    decision = recognize_intent("", CAPS)
    assert decision.can_do == "needs_input"
    assert decision.intent == "unknown"


def test_recognize_intent_cve_russian_task() -> None:
    decision = recognize_intent(
        r"проверь на cve артефакты D:\artifacts\demo.rpm", CAPS
    )
    assert decision.intent == "evidence.cve_scan"
    assert decision.can_do == "yes"
    assert decision.confidence > 0.5


def test_recognize_intent_logs_latest_phrase() -> None:
    decision = recognize_intent("покажи последние логи", CAPS)
    assert decision.intent == "logs.latest"
    assert decision.requires_apply is False


def test_recognize_intent_preview_code_change() -> None:
    decision = recognize_intent("preview fix bug in patcher.py", CAPS)
    assert decision.intent == "run.preview"
    assert decision.requires_apply is False


def test_recognize_intent_artifacts_inspect_detects_path() -> None:
    decision = recognize_intent(
        r"проведи анализ артефактов отсюда D:\data\archives", CAPS
    )
    assert decision.intent == "evidence.artifacts.inspect"
    assert decision.can_do == "yes"


def test_recognize_intent_json_compare_two_paths() -> None:
    decision = recognize_intent(
        r"сравни D:\reports\left.json и D:\reports\right.json", CAPS
    )
    assert decision.intent == "evidence.json_compare"


def test_recognize_intent_unknown_task_returns_partial() -> None:
    decision = recognize_intent("xyzzy frobnicate quux", CAPS)
    assert decision.can_do in {"partial", "needs_input"}


def test_recognize_intent_returns_intent_decision() -> None:
    decision = recognize_intent("doctor", CAPS)
    assert isinstance(decision, IntentDecision)


def test_decision_as_dict_contains_all_fields() -> None:
    decision = recognize_intent("doctor", CAPS)
    d = decision_as_dict(decision)
    for field in ("can_do", "intent", "confidence", "requires_apply", "requires_exec"):
        assert field in d


# ---------------------------------------------------------------------------
# Path extraction helpers
# ---------------------------------------------------------------------------

def test_extract_artifact_input_path_windows_path() -> None:
    text = r'запусти cve на "D:\artifacts\bundle.rpm"'
    path = extract_artifact_input_path(text)
    assert "bundle.rpm" in path


def test_extract_artifact_output_path_second_path() -> None:
    text = r"inspect D:\src D:\dest --extract"
    out = extract_artifact_output_path(text)
    assert "dest" in out


def test_extract_artifact_input_path_empty_when_no_path() -> None:
    path = extract_artifact_input_path("сделай preview")
    assert path == ""


# ---------------------------------------------------------------------------
# Missing inputs validation
# ---------------------------------------------------------------------------

def test_cve_scan_capability_requires_input_root() -> None:
    decision = recognize_intent("проверь на cve уязвимости", CAPS)
    assert decision.intent == "evidence.cve_scan"
    assert "input_root" in decision.missing_inputs
    assert decision.can_do == "needs_input"

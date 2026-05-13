from __future__ import annotations

from local_codex_lite.capabilities import default_capabilities
from local_codex_lite.intent import extract_artifact_input_path, extract_artifact_output_path, recognize_intent


def test_capability_registry_contains_expected_ids() -> None:
    ids = {item.id for item in default_capabilities()}
    assert "run.preview" in ids
    assert "run.apply" in ids
    assert "run.exec" in ids
    assert "review.code" in ids
    assert "logs.latest" in ids
    assert "evidence.json_compare" in ids
    assert "evidence.artifacts.inspect" in ids
    assert "evidence.cve_scan" in ids
    assert "doctor" in ids
    assert "config.show" in ids


def test_recognize_latest_logs() -> None:
    decision = recognize_intent("покажи последние логи", default_capabilities())
    assert decision.intent == "logs.latest"
    assert decision.can_do == "yes"


def test_recognize_json_compare_without_paths_needs_input() -> None:
    decision = recognize_intent("сравни json", default_capabilities())
    assert decision.intent == "evidence.json_compare"
    assert decision.can_do == "needs_input"
    assert "left_path" in decision.missing_inputs


def test_recognize_bug_fix_maps_to_preview_flow() -> None:
    decision = recognize_intent("исправь баг в patcher.py", default_capabilities())
    assert decision.intent == "run.preview"
    assert decision.requires_apply is False


def test_recognize_code_review_maps_to_review_flow() -> None:
    decision = recognize_intent("сделай обзор кода для pull request", default_capabilities())
    assert decision.intent == "review.code"
    assert decision.requires_apply is False
    assert decision.requires_exec is False


def test_recognize_cve_scan_with_path() -> None:
    decision = recognize_intent(r"проверь на cve артефакты из D:\artifacts\bundle", default_capabilities())
    assert decision.intent == "evidence.cve_scan"
    assert decision.can_do == "yes"


def test_recognize_unknown_task_returns_partial() -> None:
    decision = recognize_intent("расскажи что-нибудь странное про абстрактные галактики", default_capabilities())
    assert decision.can_do == "partial"
    assert decision.intent == "unknown"

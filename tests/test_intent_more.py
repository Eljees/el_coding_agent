"""Additional coverage for intent.py — uncovered branches."""

from __future__ import annotations

from local_codex_lite.capabilities import default_capabilities
from local_codex_lite.intent import recognize_intent

CAPS = default_capabilities()


def test_recognize_intent_empty_capabilities_returns_needs_input() -> None:
    decision = recognize_intent("fix something", [])
    assert decision.can_do == "needs_input"
    assert decision.intent == "unknown"
    assert "No capabilities" in decision.human_summary


def test_recognize_intent_review_pr_phrase_boosts_score() -> None:
    decision = recognize_intent("review pr", CAPS)
    assert decision.intent == "review.code"
    assert "phrase:pr" in decision.matched_keywords


def test_recognize_intent_artifacts_inspect_without_path_sets_safe_action() -> None:
    decision = recognize_intent("inspect artifacts", CAPS)
    assert decision.intent == "evidence.artifacts.inspect"
    assert "input_root" in decision.missing_inputs
    assert "artifacts inspect" in decision.safe_next_action


def test_recognize_intent_apply_capability_has_requires_apply_risk() -> None:
    # "добавь ... примени" triggers run.apply (requires_apply=True) → risks list
    decision = recognize_intent("добавь изменения и примени", CAPS)
    assert decision.requires_apply is True
    assert any("--apply" in r for r in decision.risks)

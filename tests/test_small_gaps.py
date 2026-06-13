"""Targeted tests for small remaining coverage gaps across multiple modules."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# evidence_mode.py:111 — save_report_json
# ---------------------------------------------------------------------------


def test_save_report_json_writes_file(tmp_path: Path) -> None:
    from local_codex_lite.evidence_mode import create_evidence_bundle, save_report_json

    bundle = create_evidence_bundle(tmp_path, source="test", task="task")
    path = save_report_json(bundle, "report.json", {"status": "ok"})
    assert path.exists()
    assert path.name == "report.json"


# ---------------------------------------------------------------------------
# evidence_mode.py:116 — list_evidence_artifacts with missing bundle_dir
# ---------------------------------------------------------------------------


def test_list_evidence_artifacts_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    from local_codex_lite.evidence_mode import list_evidence_artifacts

    result = list_evidence_artifacts(tmp_path / "nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# evidence_mode.py:145 — _record_artifact early return when metadata missing
# ---------------------------------------------------------------------------


def test_record_artifact_skips_when_metadata_path_missing(tmp_path: Path) -> None:
    from local_codex_lite.evidence_mode import create_evidence_bundle, save_raw_text

    bundle = create_evidence_bundle(tmp_path, source="test", task="task")
    bundle.metadata_path.unlink()
    path = save_raw_text(bundle, "raw.txt", "hello")
    assert path.exists()


# ---------------------------------------------------------------------------
# lessons.py:308 — load_learned skips record with missing signature
# ---------------------------------------------------------------------------


def test_load_learned_skips_records_without_signature(tmp_path: Path) -> None:
    import json

    from local_codex_lite.lessons import load_learned

    store = tmp_path / ".local-codex-lite" / "lessons.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps({"ts": 1.0, "error_code": "ctx"})
        + "\n"
        + json.dumps(
            {
                "ts": 2.0,
                "signature": "valid sig",
                "error_code": "ctx",
                "detail_excerpt": "x",
                "task_excerpt": "t",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    lessons = load_learned(tmp_path)
    assert len(lessons) == 1
    assert lessons[0].signature == "valid sig"


# ---------------------------------------------------------------------------
# lessons.py:373 — relevant_lessons breaks when limit reached in learned loop
# ---------------------------------------------------------------------------


def test_relevant_lessons_stops_at_max_items_in_learned_loop(tmp_path: Path) -> None:
    import json

    from local_codex_lite.lessons import relevant_lessons

    store = tmp_path / ".local-codex-lite" / "lessons.jsonl"
    store.parent.mkdir(parents=True)
    records = [
        {
            "ts": float(i),
            "signature": f"sig_{i}",
            "error_code": "ctx",
            "detail_excerpt": "fix",
            "task_excerpt": "test task",
        }
        for i in range(5)
    ]
    store.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    result = relevant_lessons(tmp_path, "test task", max_items=2)
    assert len(result) <= 2


# ---------------------------------------------------------------------------
# lessons.py:410 — load_user_rules skips empty rules after stripping
# ---------------------------------------------------------------------------


def test_load_user_rules_skips_empty_rule_after_strip(tmp_path: Path) -> None:
    from local_codex_lite.lessons import load_user_rules

    rules_file = tmp_path / "AGENT_RULES.md"
    rules_file.write_text("- valid rule\n- \n- another valid\n", encoding="utf-8")
    result = load_user_rules(tmp_path)
    assert "valid rule" in result
    assert "another valid" in result
    assert len(result) == 2


# ---------------------------------------------------------------------------
# prompts.py:39 — evidence_question_prompt delegates to ask_prompt
# ---------------------------------------------------------------------------


def test_evidence_question_prompt_returns_list_of_messages() -> None:
    from local_codex_lite.prompts import evidence_question_prompt

    result = evidence_question_prompt("what is X?", "context text", "evidence block")
    assert isinstance(result, list)
    assert len(result) >= 2
    assert any("evidence" in str(m).lower() for m in result)


# ---------------------------------------------------------------------------
# prompts.py:225 — patch_repair_prompt delegates to patch_repair_prompt_for_issue
# ---------------------------------------------------------------------------


def test_patch_repair_prompt_returns_message_list() -> None:
    from local_codex_lite.prompts import patch_repair_prompt

    result = patch_repair_prompt(
        task="fix a bug",
        plan_json='{"steps": []}',
        previous_patch="--- a/foo.py\n+++ b/foo.py",
        error="context mismatch",
        context="some context",
    )
    assert isinstance(result, list)
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# capabilities.py:347 — _load_plugin_capabilities alias
# ---------------------------------------------------------------------------


def test_load_plugin_capabilities_returns_list() -> None:
    from local_codex_lite.capabilities import _load_plugin_capabilities

    result = _load_plugin_capabilities()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# lessons.py:373 — break in learned-lessons loop when max_items reached mid-loop
# ---------------------------------------------------------------------------


def test_relevant_lessons_breaks_early_when_max_items_reached_in_learned_loop(
    tmp_path: Path,
) -> None:
    """Cover the break on lessons.py:373.

    With max_items=1 and two matching learned lessons, the first lesson fills
    the quota; the second iteration of the for-loop hits the guard and breaks.
    """
    from local_codex_lite.lessons import record_lesson, relevant_lessons

    # Use a task whose keyword won't match any curated pitfall, so selected
    # starts empty when we reach the learned-lessons loop.
    task = "zq9_unique_nonmatching_task_xyzzy"

    record_lesson(
        tmp_path,
        error_code="patch_rejected",
        detail="apply failed for zq9_unique_nonmatching_task_xyzzy run",
        task=task,
    )
    # Record a second distinct lesson so there are 2 candidates to iterate.
    record_lesson(
        tmp_path,
        error_code="timeout",
        detail="timeout during zq9_unique_nonmatching_task_xyzzy execution",
        task=task,
    )

    result = relevant_lessons(tmp_path, task, max_items=1)
    assert len(result) == 1  # only the first match; break fired on the second iteration

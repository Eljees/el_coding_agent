"""Unit coverage for the lessons memory module.

Exercises the curated-pitfall matcher, the learned JSONL store round-trip, the
relevance filter, the guardrail block rendering, dedup/cap behaviour, and the
best-effort failure handling.
"""

from __future__ import annotations

from pathlib import Path

from local_codex_lite import lessons

# ---------------------------------------------------------------------------
# Curated pitfalls
# ---------------------------------------------------------------------------


def test_curated_pitfalls_are_well_formed() -> None:
    assert len(lessons.CURATED_PITFALLS) >= 6
    for lesson in lessons.CURATED_PITFALLS:
        assert lesson.trigger_keywords
        assert lesson.guidance.strip()
        assert lesson.signature.strip()


def test_relevant_lessons_matches_curated_by_keyword(tmp_path: Path) -> None:
    items = lessons.relevant_lessons(tmp_path, "build a tkinter calculator GUI", max_items=3)
    assert any("tkinter" in item.lower() for item in items)


def test_relevant_lessons_empty_for_unrelated_task(tmp_path: Path) -> None:
    # No curated keyword and no learned store -> nothing relevant.
    assert lessons.relevant_lessons(tmp_path, "xyzzy plugh", max_items=3) == []


def test_relevant_lessons_respects_max_items(tmp_path: Path) -> None:
    # A task that hits several curated triggers must still be capped.
    task = "write a function that uses open() to read a file and import a module"
    items = lessons.relevant_lessons(tmp_path, task, max_items=2)
    assert len(items) <= 2


def test_relevant_lessons_zero_max_items(tmp_path: Path) -> None:
    assert lessons.relevant_lessons(tmp_path, "tkinter", max_items=0) == []


# ---------------------------------------------------------------------------
# Learned store round-trip
# ---------------------------------------------------------------------------


def test_record_and_load_round_trip(tmp_path: Path) -> None:
    lessons.record_lesson(
        tmp_path,
        error_code="python_syntax_error",
        detail="SyntaxError: invalid syntax at line 12 in '/abs/foo.py'",
        task="add a parser to the calculator widget",
    )
    learned = lessons.load_learned(tmp_path)
    assert len(learned) == 1
    record = learned[0]
    assert record.error_code == "python_syntax_error"
    assert record.signature  # normalized, non-empty
    assert "<n>" in record.signature  # the line number was normalized away
    assert "calculator" in record.task_excerpt


def test_record_lesson_dedups_by_signature(tmp_path: Path) -> None:
    for _ in range(3):
        lessons.record_lesson(
            tmp_path,
            error_code="post_apply_runtime",
            detail="ModuleNotFoundError: No module named 'requests'",
            task="fetch a url",
        )
    assert len(lessons.load_learned(tmp_path)) == 1


def test_record_lesson_skips_empty_signature(tmp_path: Path) -> None:
    lessons.record_lesson(tmp_path, error_code="x", detail="   \n  ", task="t")
    assert lessons.load_learned(tmp_path) == []


def test_record_lesson_excerpts_are_clamped(tmp_path: Path) -> None:
    long_detail = "ValueError: " + "x" * 500
    long_task = "y" * 500
    lessons.record_lesson(tmp_path, error_code="c", detail=long_detail, task=long_task)
    record = lessons.load_learned(tmp_path)[0]
    assert len(record.detail_excerpt) <= lessons._EXCERPT_CHARS
    assert len(record.task_excerpt) <= lessons._EXCERPT_CHARS


def test_load_learned_returns_newest_first(tmp_path: Path) -> None:
    lessons.record_lesson(tmp_path, error_code="a", detail="AlphaError happened", task="t1")
    lessons.record_lesson(tmp_path, error_code="b", detail="BravoError happened", task="t2")
    learned = lessons.load_learned(tmp_path)
    assert [item.error_code for item in learned] == ["b", "a"]


def test_load_learned_respects_limit(tmp_path: Path) -> None:
    for word in ("alpha", "bravo", "charlie"):
        lessons.record_lesson(tmp_path, error_code="c", detail=f"{word} problem", task="t")
    assert len(lessons.load_learned(tmp_path, limit=2)) == 2


def test_load_learned_tolerates_corrupt_lines(tmp_path: Path) -> None:
    store = tmp_path / lessons._STORE_DIRNAME / lessons._STORE_FILENAME
    store.parent.mkdir(parents=True)
    store.write_text(
        '{"ts": 1.0, "error_code": "c", "signature": "ok", "detail_excerpt": "d", '
        '"task_excerpt": "t"}\n'
        "not json at all\n"
        "\n"
        "[1, 2, 3]\n",
        encoding="utf-8",
    )
    learned = lessons.load_learned(tmp_path)
    assert len(learned) == 1
    assert learned[0].signature == "ok"


def test_load_learned_missing_store(tmp_path: Path) -> None:
    assert lessons.load_learned(tmp_path) == []


def test_record_lesson_enforces_file_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lessons, "_MAX_FILE_RECORDS", 3)
    for word in ("alpha", "bravo", "charlie", "delta", "echo"):
        lessons.record_lesson(tmp_path, error_code="c", detail=f"{word} broke", task="t")
    learned = lessons.load_learned(tmp_path)
    assert len(learned) == 3
    # Newest-first: the last three recorded survive.
    assert learned[0].detail_excerpt.startswith("echo")


def test_record_lesson_never_raises(tmp_path: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(lessons, "_append_line", boom)
    # Must swallow the write failure rather than propagate it.
    lessons.record_lesson(tmp_path, error_code="c", detail="ValueError boom", task="t")


# ---------------------------------------------------------------------------
# relevant_lessons against the learned store
# ---------------------------------------------------------------------------


def test_relevant_lessons_matches_learned_by_shared_word(tmp_path: Path) -> None:
    lessons.record_lesson(
        tmp_path,
        error_code="post_apply_runtime",
        detail="AttributeError: histogram object has no attribute draw",
        task="build a histogram plotting helper",
    )
    items = lessons.relevant_lessons(tmp_path, "improve the histogram rendering", max_items=3)
    assert any("post_apply_runtime" in item for item in items)


def test_relevant_lessons_ignores_unrelated_learned(tmp_path: Path) -> None:
    lessons.record_lesson(
        tmp_path,
        error_code="c",
        detail="ZetaError thing",
        task="completely unrelated database migration work",
    )
    assert lessons.relevant_lessons(tmp_path, "render a quantum sprite", max_items=3) == []


# ---------------------------------------------------------------------------
# Guardrail block
# ---------------------------------------------------------------------------


def test_guardrail_block_empty_when_nothing_relevant(tmp_path: Path) -> None:
    assert lessons.lessons_guardrail_block(tmp_path, "xyzzy plugh") == ""


def test_guardrail_block_renders_header_and_bullets(tmp_path: Path) -> None:
    block = lessons.lessons_guardrail_block(tmp_path, "make a tkinter button", max_items=3)
    assert block.startswith("Known pitfalls to avoid:")
    assert "- " in block


# ---------------------------------------------------------------------------
# clear_learned
# ---------------------------------------------------------------------------


def test_clear_learned_removes_records(tmp_path: Path) -> None:
    lessons.record_lesson(tmp_path, error_code="c", detail="ValueError boom", task="t")
    assert lessons.clear_learned(tmp_path) == 1
    assert lessons.load_learned(tmp_path) == []


def test_clear_learned_missing_store_returns_zero(tmp_path: Path) -> None:
    assert lessons.clear_learned(tmp_path) == 0

"""Tests for ``local_codex_lite.run_report``: attempt timelines + lessons stats."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from local_codex_lite.lessons import signature_for_detail
from local_codex_lite.run_report import (
    build_attempt_timeline,
    lessons_stats,
    list_run_dirs,
    load_run_events,
    render_lessons_stats,
    render_timeline,
)


def _make_run(
    workspace: Path,
    name: str,
    *,
    events: list[dict] | None = None,
    raw_event_lines: list[str] | None = None,
    task: str | None = None,
    result: dict | None = None,
    extra_files: dict[str, dict] | None = None,
) -> Path:
    run_dir = workspace / ".local-codex-lite" / "runs" / name
    run_dir.mkdir(parents=True)
    lines: list[str] = []
    for event in events or []:
        lines.append(json.dumps(event, ensure_ascii=False))
    lines.extend(raw_event_lines or [])
    if lines:
        (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if task is not None:
        (run_dir / "task.txt").write_text(task, encoding="utf-8")
    if result is not None:
        (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    for filename, payload in (extra_files or {}).items():
        (run_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
    return run_dir


def _ts(year: int, month: int, day: int) -> float:
    return datetime(year, month, day, tzinfo=UTC).timestamp()


# ---------------------------------------------------------------------------
# load_run_events
# ---------------------------------------------------------------------------


def test_load_run_events_missing_file(tmp_path: Path) -> None:
    assert load_run_events(tmp_path) == []


def test_load_run_events_tolerates_broken_lines(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        "20260101-000000",
        events=[{"stage": "plan", "attempt": 1, "status": "success"}],
        raw_event_lines=["{broken json", "[1, 2, 3]", "", '"just a string"'],
    )
    events = load_run_events(run_dir)
    assert events == [{"stage": "plan", "attempt": 1, "status": "success"}]


# ---------------------------------------------------------------------------
# build_attempt_timeline
# ---------------------------------------------------------------------------


def test_timeline_clean_run(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        "20260101-000000",
        events=[
            {"stage": "plan", "attempt": 1, "status": "success"},
            {"stage": "patch", "attempt": 1, "status": "success"},
        ],
        task="add a   readme " + "x" * 200,
        result={"applied": True},
    )
    report = build_attempt_timeline(run_dir)
    assert report.run_id == "20260101-000000"
    assert len(report.task_excerpt) == 80  # collapsed + clamped
    assert [row.status for row in report.rows] == ["ok", "ok"]
    assert report.final_status == "applied"
    assert report.repair_count == 0


def test_timeline_counts_repairs_and_keeps_error_codes(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        "20260102-000000",
        events=[
            {"stage": "plan", "attempt": 1, "status": "success"},
            {
                "stage": "post_apply_smoke",
                "status": "patch_error",
                "patch_error_code": "post_apply_runtime",
                "raw_error": "TclError: unknown option -contextmenu",
                "repair_attempt": 1,
            },
            {"stage": "patch", "attempt": 2, "status": "success"},
        ],
        result={"applied": True, "patch_attempts": 2},
    )
    report = build_attempt_timeline(run_dir)
    failed = report.rows[1]
    assert failed.status == "patch_error"
    assert failed.attempt == 1
    assert failed.error_code == "post_apply_runtime"
    assert failed.detail_excerpt is not None and "TclError" in failed.detail_excerpt
    assert report.repair_count == 1
    assert report.final_status == "applied"


def test_timeline_enriches_missing_detail_from_issue_json(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        "20260103-000000",
        events=[
            {
                "stage": "apply",
                "status": "patch_error",
                "patch_error_code": "apply_failed",
                "repair_attempt": 1,
            }
        ],
        extra_files={
            "apply_issue.json": {
                "patch_error": {"code": "apply_failed", "detail": "git apply rejected"},
                "stderr": "error: patch failed: foo.py:1",
            }
        },
    )
    report = build_attempt_timeline(run_dir)
    assert report.rows[0].detail_excerpt == "error: patch failed: foo.py:1"


def test_timeline_final_status_variants(tmp_path: Path) -> None:
    failed = _make_run(
        tmp_path,
        "20260104-000000",
        result={"applied": False},
        extra_files={"failure.json": {"stage": "apply", "patch_error": {"code": "x"}}},
    )
    preview = _make_run(tmp_path, "20260105-000000", result={"dry_run": True})
    partial = _make_run(tmp_path, "20260106-000000", result={"applied": False})
    empty = _make_run(tmp_path, "20260107-000000")
    assert build_attempt_timeline(failed).final_status == "failed"
    assert build_attempt_timeline(preview).final_status == "preview"
    assert build_attempt_timeline(partial).final_status == "partial"
    assert build_attempt_timeline(empty).final_status == "unknown"


def test_list_run_dirs_newest_first_with_limit(tmp_path: Path) -> None:
    for name in ("20260101-000000", "20260103-000000", "20260102-000000"):
        _make_run(tmp_path, name)
    names = [path.name for path in list_run_dirs(tmp_path, limit=2)]
    assert names == ["20260103-000000", "20260102-000000"]
    assert list_run_dirs(tmp_path / "nowhere") == []


# ---------------------------------------------------------------------------
# render_timeline
# ---------------------------------------------------------------------------


def test_render_timeline_text(tmp_path: Path) -> None:
    run_dir = _make_run(
        tmp_path,
        "20260108-000000",
        events=[
            {"stage": "plan", "attempt": 1, "status": "success"},
            {
                "stage": "post_apply_syntax",
                "status": "patch_error",
                "patch_error_code": "python_syntax_error",
                "raw_error": "SyntaxError: invalid syntax",
                "repair_attempt": 1,
            },
            {"stage": "patch", "attempt": 2, "status": "success"},
        ],
        task="fix the bug",
        result={"applied": True},
    )
    text = render_timeline(build_attempt_timeline(run_dir))
    assert "run: 20260108-000000" in text
    assert "task: fix the bug" in text
    assert "plan #1 ok" in text
    assert "post_apply_syntax #1 FAILED python_syntax_error: SyntaxError: invalid syntax" in text
    assert "patch #2 ok" in text
    assert text.endswith("result: applied after 1 repair")


def test_render_timeline_empty_run(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, "20260109-000000")
    text = render_timeline(build_attempt_timeline(run_dir))
    assert "(no events recorded)" in text
    assert text.endswith("result: unknown")


# ---------------------------------------------------------------------------
# lessons_stats
# ---------------------------------------------------------------------------


def _write_lesson(workspace: Path, *, ts: float, signature: str, error_code: str = "e") -> None:
    store = workspace / ".local-codex-lite" / "lessons.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": ts,
        "error_code": error_code,
        "signature": signature,
        "detail_excerpt": "detail",
        "task_excerpt": "task",
    }
    with store.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def test_lessons_stats_empty_workspace(tmp_path: Path) -> None:
    stats = lessons_stats(tmp_path)
    assert stats.lessons == []
    assert stats.runs_scanned == 0
    assert stats.runs_with_errors == 0
    assert stats.repair_successes == 0
    assert stats.top_signatures == []


def test_lessons_stats_before_and_after(tmp_path: Path) -> None:
    detail = "ValueError: boom"
    signature = signature_for_detail(detail)
    error_event = {
        "stage": "apply",
        "status": "patch_error",
        "patch_error_code": "apply_failed",
        "raw_error": detail,
        "repair_attempt": 1,
    }
    # One failing run before the lesson, one after; the early run recovers
    # (applied after repair) so it also counts as a repair success.
    _make_run(tmp_path, "20260101-000000", events=[error_event], result={"applied": True})
    _make_run(tmp_path, "20260301-000000", events=[error_event], result={"applied": False})
    _write_lesson(tmp_path, ts=_ts(2026, 2, 1), signature=signature, error_code="apply_failed")

    stats = lessons_stats(tmp_path)
    assert stats.runs_scanned == 2
    assert stats.runs_with_errors == 2
    assert stats.repair_successes == 1
    assert len(stats.lessons) == 1
    lesson = stats.lessons[0]
    assert lesson.signature == signature
    assert lesson.before == 1
    assert lesson.after == 1
    assert not lesson.holding
    assert stats.top_signatures[0] == (signature, 2)


def test_lessons_stats_holding_lesson_and_issue_json_source(tmp_path: Path) -> None:
    detail = "TypeError: bad widget option"
    signature = signature_for_detail(detail)
    # The error is only recorded via smoke_issue.json (raw multi-line detail),
    # not via events.jsonl -- the issue files must still feed the counters.
    _make_run(
        tmp_path,
        "20260101-000000",
        extra_files={
            "smoke_issue.json": {
                "patch_error": {"code": "post_apply_runtime"},
                "detail": detail,
            }
        },
    )
    _write_lesson(tmp_path, ts=_ts(2026, 2, 1), signature=signature)
    # A later clean run must not count against the lesson.
    _make_run(tmp_path, "20260301-000000", result={"applied": True})

    stats = lessons_stats(tmp_path)
    assert stats.runs_scanned == 2
    assert stats.runs_with_errors == 1
    lesson = stats.lessons[0]
    assert lesson.before == 1
    assert lesson.after == 0
    assert lesson.holding


def test_lessons_stats_same_signature_counted_once_per_run(tmp_path: Path) -> None:
    detail = "KeyError: missing"
    error_event = {
        "stage": "apply",
        "status": "patch_error",
        "patch_error_code": "apply_failed",
        "raw_error": detail,
        "repair_attempt": 1,
    }
    _make_run(
        tmp_path,
        "20260101-000000",
        events=[error_event, dict(error_event, repair_attempt=2)],
        extra_files={
            "apply_issue.json": {"patch_error": {"code": "apply_failed"}, "stderr": detail}
        },
    )
    stats = lessons_stats(tmp_path)
    assert stats.top_signatures == [(signature_for_detail(detail), 1)]


# ---------------------------------------------------------------------------
# render_lessons_stats
# ---------------------------------------------------------------------------


def test_render_lessons_stats_table_and_summary(tmp_path: Path) -> None:
    detail = "ValueError: boom"
    signature = signature_for_detail(detail)
    error_event = {
        "stage": "apply",
        "status": "patch_error",
        "patch_error_code": "apply_failed",
        "raw_error": detail,
        "repair_attempt": 1,
    }
    _make_run(tmp_path, "20260101-000000", events=[error_event], result={"applied": True})
    _make_run(tmp_path, "20260301-000000", events=[error_event], result={"applied": False})
    _write_lesson(tmp_path, ts=_ts(2026, 2, 1), signature=signature)
    _write_lesson(tmp_path, ts=_ts(2026, 4, 1), signature="never seen again")

    text = render_lessons_stats(lessons_stats(tmp_path))
    assert "before" in text and "after" in text and "verdict" in text
    assert "✗ recurring" in text
    assert "✓ holding" in text
    assert "lessons: 2" in text
    assert "runs scanned: 2" in text
    assert "runs with errors: 2" in text
    assert "repair successes: 1" in text
    assert "top recurring signatures:" in text


def test_render_lessons_stats_empty(tmp_path: Path) -> None:
    text = render_lessons_stats(lessons_stats(tmp_path))
    assert "No learned lessons recorded yet." in text
    assert "lessons: 0" in text

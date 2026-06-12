"""Additional coverage for run_report.py — uncovered timeline and signature branches."""

from __future__ import annotations

import json
from pathlib import Path


def _make_run_dir(tmp_path: Path, events: list[dict], *, issue_files: dict[str, object] | None = None) -> Path:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260601-120000"
    run_dir.mkdir(parents=True)
    events_path = run_dir / "events.jsonl"
    events_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    if issue_files:
        for name, content in issue_files.items():
            (run_dir / name).write_text(json.dumps(content), encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# build_attempt_timeline — else branch for non-patch_error status (lines 253-254)
# ---------------------------------------------------------------------------


def test_build_attempt_timeline_else_branch_for_request_error(tmp_path: Path) -> None:
    from local_codex_lite.run_report import build_attempt_timeline

    events = [{"stage": "plan", "attempt": 1, "status": "request_error", "issue_type": "api_timeout", "error": "connection timed out"}]
    run_dir = _make_run_dir(tmp_path, events)
    report = build_attempt_timeline(run_dir)
    assert report.rows
    row = report.rows[0]
    assert row.error_code == "api_timeout"
    assert row.detail_excerpt is not None
    assert "timed out" in (row.detail_excerpt or "")


# ---------------------------------------------------------------------------
# _error_signatures — status not in _FAILURE_STATUSES continues (line 331)
# ---------------------------------------------------------------------------


def test_error_signatures_skips_non_failure_status_events(tmp_path: Path) -> None:
    from local_codex_lite.run_report import _error_signatures

    events = [
        {"status": "success", "detail": "should not be counted"},
        {"status": "patch_error", "raw_error": "context mismatch error"},
    ]
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sigs = _error_signatures(events, run_dir)
    assert not any("should not be counted" in s for s in sigs)
    assert sigs


# ---------------------------------------------------------------------------
# _error_signatures — non-dict issue JSON is skipped (line 339)
# ---------------------------------------------------------------------------


def test_error_signatures_skips_non_dict_issue_json(tmp_path: Path) -> None:
    from local_codex_lite.run_report import _error_signatures

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "test_issue.json").write_text("null", encoding="utf-8")
    sigs = _error_signatures([], run_dir)
    assert sigs == set()

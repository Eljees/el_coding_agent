"""Additional coverage for logging_utils.py — uncovered utility paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from local_codex_lite.logging_utils import (
    _collect_artifacts,
    _jsonable,
    _read_text_if_exists,
    append_jsonl,
    dump_json,
    latest_events_path,
    latest_session_dir,
    resolve_run_dir,
    run_summary,
    sanitize_log_text,
    tail_events_text,
)

# ---------------------------------------------------------------------------
# sanitize_log_text — empty input and truncation
# ---------------------------------------------------------------------------


def test_sanitize_log_text_returns_empty_string_for_empty_input() -> None:
    assert sanitize_log_text("") == ""
    assert sanitize_log_text("   ") == ""


def test_sanitize_log_text_truncates_long_input() -> None:
    long_text = "x" * 700
    result = sanitize_log_text(long_text, limit=600)
    assert len(result) == 600
    assert result.endswith("...")


# ---------------------------------------------------------------------------
# latest_session_dir — no runs directory and empty runs directory
# ---------------------------------------------------------------------------


def test_latest_session_dir_returns_none_when_no_runs_dir(tmp_path: Path) -> None:
    assert latest_session_dir(tmp_path) is None


def test_latest_session_dir_returns_none_when_runs_dir_empty(tmp_path: Path) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    runs.mkdir(parents=True)
    assert latest_session_dir(tmp_path) is None


# ---------------------------------------------------------------------------
# latest_events_path — no run dir
# ---------------------------------------------------------------------------


def test_latest_events_path_returns_none_when_no_runs(tmp_path: Path) -> None:
    assert latest_events_path(tmp_path) is None


def test_latest_events_path_returns_none_when_events_missing(tmp_path: Path) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    (runs / "20260101-000000").mkdir(parents=True)
    assert latest_events_path(tmp_path) is None


# ---------------------------------------------------------------------------
# resolve_run_dir — absolute path and relative path
# ---------------------------------------------------------------------------


def test_resolve_run_dir_returns_absolute_path_when_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "my_run"
    run_dir.mkdir()
    result = resolve_run_dir(tmp_path, str(run_dir))
    assert result == run_dir


def test_resolve_run_dir_returns_none_for_nonexistent_absolute(tmp_path: Path) -> None:
    nonexistent = tmp_path / "ghost"
    result = resolve_run_dir(tmp_path, str(nonexistent))
    assert result is None


def test_resolve_run_dir_finds_run_by_id(tmp_path: Path) -> None:
    runs = tmp_path / ".local-codex-lite" / "runs"
    run_dir = runs / "20260601-120000"
    run_dir.mkdir(parents=True)
    result = resolve_run_dir(tmp_path, "20260601-120000")
    assert result == run_dir


# ---------------------------------------------------------------------------
# tail_events_text — non-existent file and existing file
# ---------------------------------------------------------------------------


def test_tail_events_text_returns_empty_string_for_missing_file(tmp_path: Path) -> None:
    assert tail_events_text(tmp_path / "no_events.jsonl") == ""


def test_tail_events_text_returns_last_n_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("".join(f'{{"i":{i}}}\n' for i in range(10)), encoding="utf-8")
    result = tail_events_text(path, lines=3)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert len(lines) == 3
    assert '"i":9' in lines[-1]


# ---------------------------------------------------------------------------
# run_summary — patch_error dict/attr branches and status variants
# ---------------------------------------------------------------------------


def test_run_summary_patch_error_from_dict(tmp_path: Path) -> None:
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    import json

    (run_dir / "result.json").write_text(
        json.dumps({"patch_error": {"code": "syntax_error"}}), encoding="utf-8"
    )
    summary = run_summary(run_dir)
    assert summary["patch_error_code"] == "syntax_error"


def test_run_summary_patch_error_from_attribute(tmp_path: Path) -> None:
    run_dir = tmp_path / "run2"
    run_dir.mkdir()

    @dataclass
    class FakeError:
        code: str

    import json
    from unittest.mock import patch

    err_obj = FakeError(code="oserror")
    orig = __import__("json").loads

    def fake_loads(text: str):  # type: ignore[return]
        data = orig(text)
        if isinstance(data, dict) and "patch_error" in data:
            data["patch_error"] = err_obj
        return data

    (run_dir / "result.json").write_text('{"patch_error": {}}', encoding="utf-8")
    with patch("local_codex_lite.logging_utils.json.loads", side_effect=fake_loads):
        summary = run_summary(run_dir)
    assert summary["patch_error_code"] == "oserror"


def test_run_summary_status_dry_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run3"
    run_dir.mkdir()
    import json

    (run_dir / "result.json").write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    summary = run_summary(run_dir)
    assert summary["status"] == "dry_run"


def test_run_summary_status_ok_for_non_empty_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "run4"
    run_dir.mkdir()
    import json

    (run_dir / "result.json").write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    summary = run_summary(run_dir)
    assert summary["status"] == "ok"


# ---------------------------------------------------------------------------
# _jsonable — tuple handling
# ---------------------------------------------------------------------------


def test_jsonable_converts_tuple_to_list() -> None:
    result = _jsonable((1, "two", 3.0))
    assert result == [1, "two", 3.0]


def test_jsonable_converts_nested_tuple() -> None:
    result = _jsonable({"data": (1, 2)})
    assert result == {"data": [1, 2]}


# ---------------------------------------------------------------------------
# _read_text_if_exists — missing file
# ---------------------------------------------------------------------------


def test_read_text_if_exists_returns_none_for_missing(tmp_path: Path) -> None:
    result = _read_text_if_exists(tmp_path / "no_such_file.txt")
    assert result is None


# ---------------------------------------------------------------------------
# _collect_artifacts — non-existent run dir
# ---------------------------------------------------------------------------


def test_collect_artifacts_returns_empty_for_missing_run_dir(tmp_path: Path) -> None:
    result = _collect_artifacts(tmp_path / "no_such_run")
    assert result == []


# ---------------------------------------------------------------------------
# dump_json / append_jsonl — smoke
# ---------------------------------------------------------------------------


def test_dump_json_writes_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    dump_json(path, {"key": "value", "num": 42})
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["key"] == "value"


def test_append_jsonl_accumulates_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"b": 2})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

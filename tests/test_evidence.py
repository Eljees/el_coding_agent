from __future__ import annotations

from pathlib import Path

from local_codex_lite.evidence import compare_json_files, compare_json_values


def test_compare_json_values_reports_nested_change() -> None:
    comparison = compare_json_values(
        {"a": 1, "nested": {"x": 1}},
        {"a": 1, "nested": {"x": 2, "y": 3}},
    )

    assert comparison.same is False
    assert comparison.summary["changed"] == 1
    assert comparison.summary["added"] == 1
    assert any(change["path"] == "$.nested.x" for change in comparison.changes)


def test_compare_json_files_reports_added_key(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"a": 1}', encoding="utf-8")
    right.write_text('{"a": 1, "b": 2}', encoding="utf-8")

    comparison = compare_json_files(left, right)

    assert comparison.same is False
    assert comparison.summary["added"] == 1
    assert comparison.changes[0]["kind"] == "added"

"""Additional coverage for evidence.py — list comparisons, label branch,
_compact_value edge cases not hit by existing tests."""

from __future__ import annotations

from pathlib import Path

from local_codex_lite.evidence import (
    compare_json_values,
    compare_json_values_as_dict,
    evidence_dir,
    save_evidence,
)

# ---------------------------------------------------------------------------
# evidence_dir — with label (line 30)
# ---------------------------------------------------------------------------


def test_evidence_dir_with_label_creates_subdirectory(tmp_path: Path) -> None:
    result = evidence_dir(tmp_path, label="phase1")
    assert result == tmp_path / "evidence" / "phase1"
    assert result.is_dir()


def test_evidence_dir_without_label_creates_base(tmp_path: Path) -> None:
    result = evidence_dir(tmp_path)
    assert result == tmp_path / "evidence"
    assert result.is_dir()


def test_save_evidence_creates_json_in_evidence_dir(tmp_path: Path) -> None:
    path = save_evidence(tmp_path, "results", {"score": 42})
    assert path == tmp_path / "evidence" / "results.json"
    assert path.read_text(encoding="utf-8").strip().startswith("{")


# ---------------------------------------------------------------------------
# _compare_value — type_changed case (lines 74-83)
# ---------------------------------------------------------------------------


def test_compare_json_values_type_changed() -> None:
    comparison = compare_json_values({"a": 1}, {"a": "one"})
    assert comparison.same is False
    assert comparison.summary["type_changed"] == 1
    change = next(c for c in comparison.changes if c["path"] == "$.a")
    assert change["kind"] == "type_changed"
    assert change["left"] == 1
    assert change["right"] == "one"


def test_compare_json_values_top_level_type_changed() -> None:
    comparison = compare_json_values([1, 2], {"a": 1})
    assert not comparison.same
    assert comparison.summary["type_changed"] == 1


# ---------------------------------------------------------------------------
# _compare_value — dict key removed (lines 89-90)
# ---------------------------------------------------------------------------


def test_compare_json_values_dict_key_removed() -> None:
    comparison = compare_json_values({"a": 1, "b": 2}, {"a": 1})
    assert comparison.same is False
    assert comparison.summary["removed"] == 1
    removed = [c for c in comparison.changes if c["kind"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["path"] == "$.b"
    assert removed[0]["left"] == 2
    assert removed[0]["right"] is None


# ---------------------------------------------------------------------------
# _compare_value — list comparisons (lines 117-140)
# ---------------------------------------------------------------------------


def test_compare_json_values_list_item_added() -> None:
    comparison = compare_json_values([1, 2], [1, 2, 3])
    assert not comparison.same
    assert comparison.summary["added"] == 1
    added = [c for c in comparison.changes if c["kind"] == "added"]
    assert added[0]["path"] == "$[2]"
    assert added[0]["right"] == 3


def test_compare_json_values_list_item_removed() -> None:
    comparison = compare_json_values([1, 2, 3], [1, 2])
    assert not comparison.same
    assert comparison.summary["removed"] == 1
    removed = [c for c in comparison.changes if c["kind"] == "removed"]
    assert removed[0]["path"] == "$[2]"
    assert removed[0]["left"] == 3


def test_compare_json_values_list_mixed_changes() -> None:
    comparison = compare_json_values([1, 2, 3], [1, 9, 3, 4])
    assert not comparison.same
    assert comparison.summary["changed"] >= 1
    assert comparison.summary["added"] >= 1


def test_compare_json_values_nested_list_in_dict() -> None:
    comparison = compare_json_values({"items": [1, 2]}, {"items": [1, 2, 3]})
    assert not comparison.same
    added = [c for c in comparison.changes if c["kind"] == "added"]
    assert any("items[2]" in c["path"] for c in added)


def test_compare_json_values_identical_lists() -> None:
    comparison = compare_json_values([1, 2, 3], [1, 2, 3])
    assert comparison.same
    assert comparison.changes == []


# ---------------------------------------------------------------------------
# _compact_value — dict/list value and repr branch (line 158)
# ---------------------------------------------------------------------------


def test_compare_json_values_compact_value_dict_branch() -> None:
    comparison = compare_json_values({"nested": {"x": 1}}, {"other": 2})
    removed = [c for c in comparison.changes if c["kind"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["left"] == {"x": 1}


def test_compare_json_values_compact_value_list_branch() -> None:
    comparison = compare_json_values({"items": [1, 2, 3]}, {"items": "gone"})
    type_changed = [c for c in comparison.changes if c["kind"] == "type_changed"]
    assert type_changed[0]["left"] == [1, 2, 3]


def test_compare_json_values_compact_value_repr_branch() -> None:
    comparison = compare_json_values((1, 2), "other_type")
    assert not comparison.same
    type_changed = comparison.changes[0]
    assert type_changed["kind"] == "type_changed"
    assert type_changed["left"] == repr((1, 2))


# ---------------------------------------------------------------------------
# compare_json_values_as_dict — smoke test
# ---------------------------------------------------------------------------


def test_compare_json_values_as_dict_returns_dict() -> None:
    result = compare_json_values_as_dict({"a": 1}, {"a": 2})
    assert isinstance(result, dict)
    assert result["same"] is False
    assert "summary" in result
    assert "changes" in result

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JsonComparison:
    same: bool
    summary: dict[str, int]
    changes: list[dict[str, Any]]


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_file(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def evidence_dir(run_root: Path, label: str | None = None) -> Path:
    base = run_root / "evidence"
    if label:
        base = base / label
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_evidence(run_root: Path, label: str, data: Any) -> Path:
    return save_json_file(evidence_dir(run_root) / f"{label}.json", data)


def compare_json_files(left_path: Path, right_path: Path) -> JsonComparison:
    left = load_json_file(left_path)
    right = load_json_file(right_path)
    return compare_json_values(left, right)


def compare_json_values(left: Any, right: Any) -> JsonComparison:
    summary: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []
    _compare_value(left, right, path="$", summary=summary, changes=changes)
    return JsonComparison(
        same=not changes,
        summary=dict(summary),
        changes=changes,
    )


def compare_json_values_as_dict(left: Any, right: Any) -> dict[str, Any]:
    comparison = compare_json_values(left, right)
    return {
        "same": comparison.same,
        "summary": comparison.summary,
        "changes": comparison.changes,
    }


def _compare_value(
    left: Any,
    right: Any,
    *,
    path: str,
    summary: Counter[str],
    changes: list[dict[str, Any]],
) -> None:
    if type(left) is not type(right):
        summary["type_changed"] += 1
        changes.append(
            {
                "path": path,
                "kind": "type_changed",
                "left": _compact_value(left),
                "right": _compact_value(right),
            }
        )
        return

    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(left_keys - right_keys):
            summary["removed"] += 1
            changes.append(
                {
                    "path": f"{path}.{key}",
                    "kind": "removed",
                    "left": _compact_value(left[key]),
                    "right": None,
                }
            )
        for key in sorted(right_keys - left_keys):
            summary["added"] += 1
            changes.append(
                {
                    "path": f"{path}.{key}",
                    "kind": "added",
                    "left": None,
                    "right": _compact_value(right[key]),
                }
            )
        for key in sorted(left_keys & right_keys):
            _compare_value(
                left[key], right[key], path=f"{path}.{key}", summary=summary, changes=changes
            )
        return

    if isinstance(left, list):
        max_len = max(len(left), len(right))
        for idx in range(max_len):
            item_path = f"{path}[{idx}]"
            if idx >= len(left):
                summary["added"] += 1
                changes.append(
                    {
                        "path": item_path,
                        "kind": "added",
                        "left": None,
                        "right": _compact_value(right[idx]),
                    }
                )
                continue
            if idx >= len(right):
                summary["removed"] += 1
                changes.append(
                    {
                        "path": item_path,
                        "kind": "removed",
                        "left": _compact_value(left[idx]),
                        "right": None,
                    }
                )
                continue
            _compare_value(left[idx], right[idx], path=item_path, summary=summary, changes=changes)
        return

    if left != right:
        summary["changed"] += 1
        changes.append(
            {
                "path": path,
                "kind": "changed",
                "left": _compact_value(left),
                "right": _compact_value(right),
            }
        )


def _compact_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return value if isinstance(value, (dict, list)) else repr(value)

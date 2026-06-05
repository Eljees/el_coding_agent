"""Tk-free persistence for the GUI: window geometry and task history.

Extracted from ``ui.py`` so the file I/O and the history list transform are
unit-testable without Tkinter.  Every writer is intentionally best-effort: a
failure to persist GUI state must never crash the app, so the savers swallow
exceptions by design.
"""

from __future__ import annotations

import json
from pathlib import Path

HISTORY_MAX = 50
HISTORY_FILE = ".local-codex-lite/task_history.json"
GEOMETRY_FILE = ".local-codex-lite/ui_geometry.txt"


def load_geometry(base_root: Path) -> str | None:
    """Return the saved Tk geometry string, or None if absent/unreadable."""
    try:
        geo = (base_root / GEOMETRY_FILE).read_text(encoding="utf-8").strip()
        return geo or None
    except Exception:
        return None


def save_geometry(base_root: Path, geometry: str) -> None:
    """Persist the window geometry string (best-effort)."""
    try:
        geo_file = base_root / GEOMETRY_FILE
        geo_file.parent.mkdir(parents=True, exist_ok=True)
        geo_file.write_text(geometry, encoding="utf-8")
    except Exception:
        pass


def load_task_history(base_root: Path) -> list[str]:
    """Load the task-history list (most-recent first), capped, or [] on any error."""
    try:
        data = json.loads((base_root / HISTORY_FILE).read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(t) for t in data][:HISTORY_MAX]
    except Exception:
        pass
    return []


def push_task(history: list[str], task: str) -> list[str]:
    """Return a new history with ``task`` moved to the front, de-duplicated and
    capped at ``HISTORY_MAX``.  An empty task leaves the history unchanged."""
    if not task:
        return list(history)
    deduped = [task] + [t for t in history if t != task]
    return deduped[:HISTORY_MAX]


def save_task_history(base_root: Path, history: list[str]) -> None:
    """Persist the task-history list as pretty JSON (best-effort)."""
    try:
        hist_file = base_root / HISTORY_FILE
        hist_file.parent.mkdir(parents=True, exist_ok=True)
        hist_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

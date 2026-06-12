"""Additional coverage for cli_logs.py and logging_utils.py — uncovered branches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch


def _make_run_dir(tmp_path: Path, *, with_events: bool = False, result: dict | None = None) -> Path:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260601-120000"
    run_dir.mkdir(parents=True)
    if result:
        (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    if with_events:
        (run_dir / "events.jsonl").write_text('{"event": "start"}\n', encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# cmd_logs_latest — events_path is None branch (lines 32-34)
# ---------------------------------------------------------------------------


def test_cmd_logs_latest_no_events_prints_summary(tmp_path: Path) -> None:
    from local_codex_lite.cli_logs import cmd_logs_latest

    _make_run_dir(tmp_path)
    args = argparse.Namespace()
    with patch("local_codex_lite.cli_logs.workspace_root", return_value=tmp_path):
        rc = cmd_logs_latest(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# cmd_logs_tail — events_path.exists() is True branch (lines 48-49)
# ---------------------------------------------------------------------------


def test_cmd_logs_tail_with_events_prints_tail(tmp_path: Path) -> None:
    from local_codex_lite.cli_logs import cmd_logs_tail

    _make_run_dir(tmp_path, with_events=True)
    args = argparse.Namespace(run=None, lines=10)
    with patch("local_codex_lite.cli_logs.workspace_root", return_value=tmp_path):
        rc = cmd_logs_tail(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# cmd_logs_show — patch_error_code branch (line 69)
# ---------------------------------------------------------------------------


def test_cmd_logs_show_prints_patch_error_code(tmp_path: Path) -> None:
    from local_codex_lite.cli_logs import cmd_logs_show

    run_dir = _make_run_dir(tmp_path, result={"patch_error": {"code": "context_mismatch"}})
    args = argparse.Namespace(run_id=str(run_dir))
    with patch("local_codex_lite.cli_logs.workspace_root", return_value=tmp_path):
        rc = cmd_logs_show(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# resolve_run_dir — relative path exists at candidate level (line 102)
# ---------------------------------------------------------------------------


def test_resolve_run_dir_returns_existing_candidate_path(tmp_path: Path) -> None:
    from local_codex_lite.logging_utils import resolve_run_dir

    # Create a directory outside of .local-codex-lite/runs so nested lookup fails
    run_dir = tmp_path / "my-custom-run"
    run_dir.mkdir()
    # Passing a relative path that exists as `candidate` but NOT under run_root
    # (workspace_root is tmp_path but "my-custom-run" is a relative Path that
    # exists via candidate.exists() check on line 102)
    import os

    prev = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = resolve_run_dir(tmp_path / "empty-workspace", "my-custom-run")
    finally:
        os.chdir(prev)
    assert result is not None
    assert result.name == "my-custom-run"

"""Tests for `local_codex_lite runs archive` / `runs prune`."""

from __future__ import annotations

import argparse
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_codex_lite import cli, runs_admin
from local_codex_lite.runs_admin import (
    archive_run,
    cmd_runs_archive,
    cmd_runs_prune,
    list_run_entries,
    select_for_archival,
)


def _make_run(
    tmp_path: Path, run_id: str, *, age_days: float = 0.0, files: dict[str, str] | None = None
) -> Path:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / run_id
    run_dir.mkdir(parents=True)
    files = files or {"task.txt": run_id, "result.json": "{}"}
    for rel, body in files.items():
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    # Backdate everything inside run_dir so mtime reflects the requested age.
    if age_days > 0:
        target_ts = time.time() - age_days * 86400
        for path in [run_dir, *run_dir.rglob("*")]:
            os.utime(path, (target_ts, target_ts))
    return run_dir


# ---------------------------------------------------------------------------
# list_run_entries / select_for_archival / archive_run
# ---------------------------------------------------------------------------


def test_list_run_entries_empty_when_no_runs(tmp_path: Path) -> None:
    assert list_run_entries(tmp_path) == []


def test_list_run_entries_reports_age(tmp_path: Path) -> None:
    _make_run(tmp_path, "20260101-010101", age_days=10)
    _make_run(tmp_path, "20260516-020202", age_days=0)
    entries = list_run_entries(tmp_path)
    assert len(entries) == 2
    ages = {e.path.name: e.age_days for e in entries}
    assert ages["20260101-010101"] >= 9.5  # rounding slack
    assert ages["20260516-020202"] < 0.5


def test_select_for_archival_threshold(tmp_path: Path) -> None:
    _make_run(tmp_path, "old", age_days=40)
    _make_run(tmp_path, "fresh", age_days=2)
    entries = list_run_entries(tmp_path)
    selected = select_for_archival(entries, older_than_days=30)
    assert [e.path.name for e in selected] == ["old"]


def test_archive_run_produces_readable_zip(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, "abc", files={"foo.txt": "hello\n", "sub/bar.txt": "bar\n"})
    archive_path = archive_run(run_dir)
    assert archive_path.exists()
    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(zf.namelist())
        # Names are relative to runs/ so they include the run-id prefix.
        assert names == sorted(["abc/foo.txt", "abc/sub/bar.txt"])
        text = zf.read("abc/foo.txt").decode("utf-8").replace("\r\n", "\n")
        assert text == "hello\n"


# ---------------------------------------------------------------------------
# cmd_runs_archive
# ---------------------------------------------------------------------------


def test_cmd_archive_returns_1_when_no_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = cmd_runs_archive(argparse.Namespace(older_than=30, apply=False, remove=False))
    assert rc == 1


def test_cmd_archive_dry_run_does_not_create_zip(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "old1", age_days=40)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = cmd_runs_archive(argparse.Namespace(older_than=30, apply=False, remove=False))
    assert rc == 0
    assert not run_dir.parent.joinpath("old1.zip").exists()
    assert run_dir.exists()  # dir not removed in dry-run


def test_cmd_archive_apply_creates_zip_keeps_dir(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "old1", age_days=40)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = cmd_runs_archive(argparse.Namespace(older_than=30, apply=True, remove=False))
    assert rc == 0
    assert (run_dir.parent / "old1.zip").exists()
    assert run_dir.exists()


def test_cmd_archive_apply_remove_deletes_dir(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "old1", age_days=40)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = cmd_runs_archive(argparse.Namespace(older_than=30, apply=True, remove=True))
    assert rc == 0
    assert (run_dir.parent / "old1.zip").exists()
    assert not run_dir.exists()


def test_cmd_archive_skips_fresh_runs(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "fresh", age_days=2)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = cmd_runs_archive(argparse.Namespace(older_than=30, apply=True, remove=True))
    assert rc == 0
    # Nothing eligible -> nothing archived, nothing removed.
    assert run_dir.exists()
    assert not (run_dir.parent / "fresh.zip").exists()


# ---------------------------------------------------------------------------
# cmd_runs_prune is archive+remove
# ---------------------------------------------------------------------------


def test_cmd_prune_apply_archives_and_removes(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "old1", age_days=40)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = cmd_runs_prune(argparse.Namespace(older_than=30, apply=True))
    assert rc == 0
    assert (run_dir.parent / "old1.zip").exists()
    assert not run_dir.exists()


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def test_build_parser_runs_archive() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["runs", "archive", "--older-than", "7", "--apply", "--remove"])
    assert ns.command == "runs"
    assert ns.runs_command == "archive"
    assert ns.older_than == 7.0
    assert ns.apply is True
    assert ns.remove is True


def test_build_parser_runs_prune_defaults() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["runs", "prune"])
    assert ns.runs_command == "prune"
    assert ns.older_than == 30.0
    assert ns.apply is False


# ---------------------------------------------------------------------------
# cmd_runs_export
# ---------------------------------------------------------------------------


def test_cmd_export_returns_1_for_missing_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_export(argparse.Namespace(run="not-there", out=None))
    assert rc == 1


def test_cmd_export_default_writes_next_to_run(tmp_path: Path, monkeypatch) -> None:
    """When --out is omitted the zip lands beside the run directory."""
    run_dir = _make_run(
        tmp_path, "20260516-101010-000000-abc", files={"task.txt": "x", "events.jsonl": "{}"}
    )
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_export(argparse.Namespace(run=run_dir.name, out=None))
    assert rc == 0
    assert (run_dir.parent / f"{run_dir.name}.zip").exists()
    assert run_dir.exists()  # source not removed
    import zipfile

    with zipfile.ZipFile(run_dir.parent / f"{run_dir.name}.zip") as zf:
        names = sorted(zf.namelist())
    assert any(n.endswith("task.txt") for n in names)
    assert any(n.endswith("events.jsonl") for n in names)


def test_cmd_export_explicit_out_file(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "20260516-aaaaaa", files={"task.txt": "x"})
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    out = tmp_path / "deliveries" / "bug-report.zip"
    rc = runs_admin.cmd_runs_export(argparse.Namespace(run=run_dir.name, out=str(out)))
    assert rc == 0
    assert out.exists()


def test_cmd_export_explicit_out_directory(tmp_path: Path, monkeypatch) -> None:
    """--out pointing at an existing directory should drop <run_id>.zip into it."""
    run_dir = _make_run(tmp_path, "20260516-bbbbbb", files={"task.txt": "x"})
    out_dir = tmp_path / "drop-here"
    out_dir.mkdir()
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_export(argparse.Namespace(run=run_dir.name, out=str(out_dir)))
    assert rc == 0
    assert (out_dir / f"{run_dir.name}.zip").exists()


def test_cmd_export_overwrites_existing_zip(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "20260516-cccccc", files={"task.txt": "first"})
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    runs_admin.cmd_runs_export(argparse.Namespace(run=run_dir.name, out=None))
    # Replace content and re-export
    (run_dir / "task.txt").write_text("second", encoding="utf-8")
    rc = runs_admin.cmd_runs_export(argparse.Namespace(run=run_dir.name, out=None))
    assert rc == 0
    import zipfile

    with zipfile.ZipFile(run_dir.parent / f"{run_dir.name}.zip") as zf:
        contents = {n: zf.read(n) for n in zf.namelist() if n.endswith("task.txt")}
    assert any(v == b"second" for v in contents.values())


# ---------------------------------------------------------------------------
# argparse wiring for runs export
# ---------------------------------------------------------------------------


def test_build_parser_runs_export_defaults() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["runs", "export"])
    assert ns.command == "runs"
    assert ns.runs_command == "export"
    assert ns.run == "latest"
    assert ns.out is None


def test_build_parser_runs_export_explicit() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["runs", "export", "--run", "20260516-111", "--out", "/tmp/x.zip"])
    assert ns.run == "20260516-111"
    assert ns.out == "/tmp/x.zip"


# ---------------------------------------------------------------------------
# select_beyond_keep / cmd_runs_cleanup
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, name: str, *, age_days: float = 0.0) -> Path:
    project_dir = tmp_path / "generated_projects" / name
    project_dir.mkdir(parents=True)
    (project_dir / "main.py").write_text("print('hi')\n", encoding="utf-8")
    if age_days > 0:
        target_ts = time.time() - age_days * 86400
        for path in [project_dir, *project_dir.rglob("*")]:
            os.utime(path, (target_ts, target_ts))
    return project_dir


def test_select_beyond_keep_returns_oldest(tmp_path: Path) -> None:
    _make_run(tmp_path, "oldest", age_days=30)
    _make_run(tmp_path, "middle", age_days=10)
    _make_run(tmp_path, "newest", age_days=1)
    entries = list_run_entries(tmp_path)
    selected = runs_admin.select_beyond_keep(entries, keep=2)
    assert [e.path.name for e in selected] == ["oldest"]


def test_select_beyond_keep_zero_selects_all(tmp_path: Path) -> None:
    _make_run(tmp_path, "a", age_days=5)
    _make_run(tmp_path, "b", age_days=1)
    entries = list_run_entries(tmp_path)
    assert len(runs_admin.select_beyond_keep(entries, keep=0)) == 2


def test_select_beyond_keep_within_limit_selects_none(tmp_path: Path) -> None:
    _make_run(tmp_path, "a", age_days=5)
    entries = list_run_entries(tmp_path)
    assert runs_admin.select_beyond_keep(entries, keep=10) == []


def test_cmd_runs_cleanup_returns_1_when_no_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_cleanup(argparse.Namespace(keep=10, apply=False))
    assert rc == 1


def test_cmd_runs_cleanup_dry_run_keeps_everything(tmp_path: Path, monkeypatch) -> None:
    old = _make_run(tmp_path, "old", age_days=30)
    fresh = _make_run(tmp_path, "fresh", age_days=1)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_cleanup(argparse.Namespace(keep=1, apply=False))
    assert rc == 0
    assert old.exists() and fresh.exists()


def test_cmd_runs_cleanup_apply_removes_oldest(tmp_path: Path, monkeypatch) -> None:
    old = _make_run(tmp_path, "old", age_days=30)
    middle = _make_run(tmp_path, "middle", age_days=10)
    fresh = _make_run(tmp_path, "fresh", age_days=1)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_cleanup(argparse.Namespace(keep=1, apply=True))
    assert rc == 0
    assert not old.exists()
    assert not middle.exists()
    assert fresh.exists()


def test_cmd_runs_cleanup_all_within_keep(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run(tmp_path, "only", age_days=5)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_runs_cleanup(argparse.Namespace(keep=10, apply=True))
    assert rc == 0
    assert run_dir.exists()


# ---------------------------------------------------------------------------
# cmd_projects_cleanup
# ---------------------------------------------------------------------------


def test_cmd_projects_cleanup_returns_1_when_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_projects_cleanup(argparse.Namespace(keep=5, apply=False))
    assert rc == 1


def test_cmd_projects_cleanup_apply_removes_oldest(tmp_path: Path, monkeypatch) -> None:
    old = _make_project(tmp_path, "20260101-000000_old", age_days=60)
    fresh = _make_project(tmp_path, "20260610-000000_fresh", age_days=1)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_projects_cleanup(argparse.Namespace(keep=1, apply=True))
    assert rc == 0
    assert not old.exists()
    assert fresh.exists()


def test_cmd_projects_cleanup_dry_run_default(tmp_path: Path, monkeypatch) -> None:
    old = _make_project(tmp_path, "20260101-000000_old", age_days=60)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    rc = runs_admin.cmd_projects_cleanup(argparse.Namespace(keep=0, apply=False))
    assert rc == 0
    assert old.exists()


# ---------------------------------------------------------------------------
# argparse wiring + dispatch for cleanup commands
# ---------------------------------------------------------------------------


def test_build_parser_runs_cleanup_defaults() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["runs", "cleanup"])
    assert ns.command == "runs"
    assert ns.runs_command == "cleanup"
    assert ns.keep == 10
    assert ns.apply is False


def test_build_parser_projects_cleanup_explicit() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["projects", "cleanup", "--keep", "3", "--apply"])
    assert ns.command == "projects"
    assert ns.projects_command == "cleanup"
    assert ns.keep == 3
    assert ns.apply is True


def test_main_dispatches_runs_cleanup(tmp_path: Path, monkeypatch) -> None:
    import sys

    _make_run(tmp_path, "only", age_days=1)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", "runs", "cleanup", "--keep", "5"])
    assert cli.main() == 0


def test_main_dispatches_projects_cleanup(tmp_path: Path, monkeypatch) -> None:
    import sys

    _make_project(tmp_path, "20260610-000000_x", age_days=1)
    monkeypatch.setattr(runs_admin, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["local-codex-lite", "projects", "cleanup"])
    assert cli.main() == 0

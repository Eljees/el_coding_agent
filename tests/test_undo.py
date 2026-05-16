"""Tests for `local_codex_lite undo` — restoring files from runs/<id>/backups/."""
from __future__ import annotations

import argparse
from pathlib import Path

from local_codex_lite import cli
from local_codex_lite.undo import collect_undo_entries


def _make_run_with_backups(tmp_path: Path, files: dict[str, str]) -> Path:
    """Lay out a fake run dir with the given relative-path -> contents in
    its backups/ directory.  Returns the run directory."""
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260516-101010-000000-abcdef"
    backups = run_dir / "backups"
    for rel, body in files.items():
        target = backups / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# collect_undo_entries
# ---------------------------------------------------------------------------

def test_collect_entries_empty_when_no_backups(tmp_path: Path) -> None:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / "20260516-101010-000000-abcdef"
    run_dir.mkdir(parents=True)
    assert collect_undo_entries(run_dir, tmp_path) == []


def test_collect_entries_lists_each_backup(tmp_path: Path) -> None:
    run_dir = _make_run_with_backups(tmp_path, {"foo.py": "old\n", "pkg/bar.py": "old\n"})
    entries = collect_undo_entries(run_dir, tmp_path)
    rels = sorted(e.workspace_path.relative_to(tmp_path).as_posix() for e in entries)
    assert rels == ["foo.py", "pkg/bar.py"]
    assert all(e.skip_reason is None for e in entries)


def test_collect_entries_flags_sensitive_destination(tmp_path: Path) -> None:
    run_dir = _make_run_with_backups(tmp_path, {".env": "SECRET=1\n"})
    entries = collect_undo_entries(run_dir, tmp_path)
    assert len(entries) == 1
    assert entries[0].skip_reason == "destination is a sensitive path"


# ---------------------------------------------------------------------------
# cmd_undo end-to-end
# ---------------------------------------------------------------------------

def test_cmd_undo_returns_1_when_no_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("local_codex_lite.undo.workspace_root", lambda: tmp_path)
    code = cli.cmd_undo(argparse.Namespace(run="latest", apply=False))
    assert code == 1


def test_cmd_undo_dry_run_does_not_touch_workspace(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run_with_backups(tmp_path, {"foo.py": "old contents\n"})
    # Workspace currently has a different version of foo.py
    (tmp_path / "foo.py").write_text("NEW contents\n", encoding="utf-8")
    monkeypatch.setattr("local_codex_lite.undo.workspace_root", lambda: tmp_path)
    code = cli.cmd_undo(argparse.Namespace(run=run_dir.name, apply=False))
    assert code == 0
    # File must NOT have been overwritten in dry-run mode.
    assert (tmp_path / "foo.py").read_text() == "NEW contents\n"


def test_cmd_undo_apply_restores_files(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run_with_backups(
        tmp_path,
        {"foo.py": "old contents\n", "pkg/bar.py": "old bar\n"},
    )
    (tmp_path / "foo.py").write_text("NEW\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "bar.py").write_text("NEW bar\n", encoding="utf-8")
    monkeypatch.setattr("local_codex_lite.undo.workspace_root", lambda: tmp_path)
    code = cli.cmd_undo(argparse.Namespace(run=run_dir.name, apply=True))
    assert code == 0
    assert (tmp_path / "foo.py").read_text() == "old contents\n"
    assert (tmp_path / "pkg" / "bar.py").read_text() == "old bar\n"


def test_cmd_undo_apply_skips_sensitive(tmp_path: Path, monkeypatch) -> None:
    run_dir = _make_run_with_backups(tmp_path, {".env": "SHOULD-NOT-RESTORE=1\n"})
    monkeypatch.setattr("local_codex_lite.undo.workspace_root", lambda: tmp_path)
    code = cli.cmd_undo(argparse.Namespace(run=run_dir.name, apply=True))
    assert code == 0
    # Sensitive file must not have been written.
    assert not (tmp_path / ".env").exists()


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def test_build_parser_undo_defaults() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["undo"])
    assert ns.command == "undo"
    assert ns.run == "latest"
    assert ns.apply is False


def test_build_parser_undo_explicit_run_and_apply() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["undo", "--run", "20260516-101010-000000-abcdef", "--apply"])
    assert ns.run == "20260516-101010-000000-abcdef"
    assert ns.apply is True

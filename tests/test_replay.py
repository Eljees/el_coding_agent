"""Tests for `local_codex_lite replay <run_id>`."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from local_codex_lite import cli, replay
from local_codex_lite.replay import _extract_touched_paths, _load_replay_inputs


def _make_source_run(tmp_path: Path, run_id: str, *, task: str, plan: dict, patch: str) -> Path:
    run_dir = tmp_path / ".local-codex-lite" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "task.txt").write_text(task, encoding="utf-8")
    (run_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (run_dir / "patch.diff").write_text(patch, encoding="utf-8")
    return run_dir


def _init_git_repo(path: Path, files: dict[str, str]) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    for rel, body in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_load_replay_inputs_returns_none_when_missing(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    # only task.txt -- the other two are missing
    (run / "task.txt").write_text("x", encoding="utf-8")
    assert _load_replay_inputs(run) is None


def test_load_replay_inputs_returns_triple(tmp_path: Path) -> None:
    run = _make_source_run(
        tmp_path,
        "r1",
        task="hello",
        plan={"summary": "p"},
        patch="diff --git a/foo b/foo\n--- a/foo\n+++ b/foo\n",
    )
    out = _load_replay_inputs(run)
    assert out is not None
    task, plan, patch = out
    assert task == "hello"
    assert plan == {"summary": "p"}
    assert "diff --git" in patch


def test_load_replay_inputs_handles_corrupt_plan(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    (run / "task.txt").write_text("x", encoding="utf-8")
    (run / "plan.json").write_text("not json at all", encoding="utf-8")
    (run / "patch.diff").write_text("diff --git a/x b/x\n", encoding="utf-8")
    assert _load_replay_inputs(run) is None


def test_extract_touched_paths_picks_up_b_paths(tmp_path: Path) -> None:
    patch = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/sub/bar.py b/sub/bar.py\n"
        "--- /dev/null\n"
        "+++ b/sub/bar.py\n"
        "@@ -0,0 +1 @@\n"
        "+hello\n"
    )
    paths = _extract_touched_paths(patch, tmp_path)
    names = sorted(str(p.relative_to(tmp_path).as_posix()) for p in paths)
    assert names == ["foo.py", "sub/bar.py"]


# ---------------------------------------------------------------------------
# cmd_replay
# ---------------------------------------------------------------------------


def test_cmd_replay_returns_1_for_missing_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(replay, "workspace_root", lambda: tmp_path)
    rc = replay.cmd_replay(
        argparse.Namespace(run_id="nope", dry_run=False, apply=False, profile=None)
    )
    assert rc == 1


def test_cmd_replay_returns_1_when_inputs_incomplete(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / ".local-codex-lite" / "runs" / "broken"
    run.mkdir(parents=True)
    (run / "task.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(replay, "workspace_root", lambda: tmp_path)
    rc = replay.cmd_replay(
        argparse.Namespace(run_id="broken", dry_run=True, apply=False, profile=None)
    )
    assert rc == 1


def test_cmd_replay_dry_run_prints_plan_and_patch(tmp_path: Path, monkeypatch, capsys) -> None:
    _init_git_repo(tmp_path, {"foo.py": "print('hi')\n"})
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-print('hi')\n"
        "+print('hello')\n"
    )
    _make_source_run(
        tmp_path, "20260516-abc", task="say hello", plan={"summary": "swap greeting"}, patch=diff
    )
    monkeypatch.setattr(replay, "workspace_root", lambda: tmp_path)
    rc = replay.cmd_replay(
        argparse.Namespace(
            run_id="20260516-abc",
            dry_run=True,
            apply=False,
            profile=None,
        )
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "swap greeting" in out
    assert "diff --git" in out
    # Dry-run must NOT actually patch the workspace.
    assert (tmp_path / "foo.py").read_text() == "print('hi')\n"


def test_cmd_replay_apply_writes_files_and_creates_run_dir(tmp_path: Path, monkeypatch) -> None:
    _init_git_repo(tmp_path, {"foo.py": "print('hi')\n"})
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-print('hi')\n"
        "+print('hello')\n"
    )
    src = _make_source_run(tmp_path, "20260516-abc", task="task", plan={"summary": "p"}, patch=diff)
    monkeypatch.setattr(replay, "workspace_root", lambda: tmp_path)
    rc = replay.cmd_replay(
        argparse.Namespace(
            run_id="20260516-abc",
            dry_run=False,
            apply=True,
            profile=None,
        )
    )
    assert rc == 0
    assert (tmp_path / "foo.py").read_text() == "print('hello')\n"
    # A new run dir distinct from the source must exist with task.txt etc.
    new_runs = sorted(
        p for p in (tmp_path / ".local-codex-lite" / "runs").iterdir() if p.is_dir() and p != src
    )
    assert len(new_runs) == 1
    new_run = new_runs[0]
    assert (new_run / "task.txt").read_text() == "task"
    assert (new_run / "replay_source.txt").read_text() == str(src)
    assert (new_run / "result.json").exists()


def test_cmd_replay_requires_apply_when_safety_demands(tmp_path: Path, monkeypatch) -> None:
    """Without --apply (and with the default require_apply_flag=True),
    cmd_replay must NOT touch the workspace."""
    _init_git_repo(tmp_path, {"foo.py": "print('hi')\n"})
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-print('hi')\n"
        "+print('hello')\n"
    )
    _make_source_run(tmp_path, "20260516-abc", task="task", plan={"summary": "p"}, patch=diff)
    monkeypatch.setattr(replay, "workspace_root", lambda: tmp_path)
    rc = replay.cmd_replay(
        argparse.Namespace(
            run_id="20260516-abc",
            dry_run=False,
            apply=False,
            profile=None,
        )
    )
    assert rc == 0
    assert (tmp_path / "foo.py").read_text() == "print('hi')\n"


def test_cmd_replay_rejects_invalid_diff(tmp_path: Path, monkeypatch) -> None:
    _init_git_repo(tmp_path, {"foo.py": "x\n"})
    _make_source_run(
        tmp_path,
        "20260516-abc",
        task="task",
        plan={"summary": "p"},
        patch="this is not a unified diff\n",
    )
    monkeypatch.setattr(replay, "workspace_root", lambda: tmp_path)
    rc = replay.cmd_replay(
        argparse.Namespace(
            run_id="20260516-abc",
            dry_run=False,
            apply=True,
            profile=None,
        )
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def test_build_parser_replay_defaults() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["replay", "latest"])
    assert ns.command == "replay"
    assert ns.run_id == "latest"
    assert ns.dry_run is False
    assert ns.apply is False
    assert ns.profile is None


def test_build_parser_replay_explicit() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["replay", "20260516-abc", "--dry-run"])
    assert ns.run_id == "20260516-abc"
    assert ns.dry_run is True
    assert ns.apply is False


def test_build_parser_replay_apply_and_profile() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["replay", "20260516-abc", "--apply", "--profile", "fast"])
    assert ns.apply is True
    assert ns.profile == "fast"

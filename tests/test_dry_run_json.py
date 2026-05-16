"""Tests for `run --dry-run --json` — machine-readable dry-run output."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from local_codex_lite import cli, runner
from local_codex_lite.config import AgentConfig


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def test_build_parser_json_flag() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "task", "--dry-run", "--json"])
    assert ns.json_output is True
    assert ns.dry_run is True


def test_build_parser_json_default_false() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "task", "--apply"])
    assert ns.json_output is False


# ---------------------------------------------------------------------------
# runner.run_task --dry-run --json end-to-end
# ---------------------------------------------------------------------------

class _StubLLM:
    """Returns one canned JSON plan for every chat() call."""

    PLAN_TEXT = (
        '{"summary":"stub-plan","files_to_inspect":["foo.py"],'
        '"implementation_steps":[],"risks":[],'
        '"needs_clarification":false,"clarifying_questions":[]}'
    )

    def __init__(self, cfg=None):
        self.config = cfg or types.SimpleNamespace(
            base_url="stub", model="stub", api_key="x", temperature=0.1,
            max_tokens=512, timeout=30, retries=0,
        )

    def chat(self, messages, max_tokens=None, status_label=None):
        return types.SimpleNamespace(text=self.PLAN_TEXT, raw={"model": "stub"})


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def test_dry_run_json_emits_one_json_document_on_stdout(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """In --dry-run --json mode the agent must put exactly one JSON document
    on real stdout; every rich/diagnostic line is supposed to go to stderr
    so the output can be piped straight into a JSON parser."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _StubLLM)
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    ns = argparse.Namespace(
        dry_run=True, apply=False, execute=False, assume_clarification=False,
        evidence_file=[], evidence_stdin=False,
        max_patch_attempts=None, json_output=True,
    )
    rc = runner.run_task("add a comment to foo.py", ns)
    out = capsys.readouterr().out
    assert rc == 0
    # The whole stdout must parse as a single JSON document.
    payload = json.loads(out)
    assert payload["task"] == "add a comment to foo.py"
    assert "plan" in payload
    assert payload["plan"]["summary"] == "stub-plan"
    assert "run_dir" in payload
    assert payload["result"]["dry_run"] is True


def test_dry_run_json_writes_run_dir_artifacts(tmp_path: Path, monkeypatch) -> None:
    """The on-disk run-dir artifacts (plan.json / result.json / events.jsonl)
    must still be written even when stdout is redirected for machine output."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _StubLLM)
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    ns = argparse.Namespace(
        dry_run=True, apply=False, execute=False, assume_clarification=False,
        evidence_file=[], evidence_stdin=False,
        max_patch_attempts=None, json_output=True,
    )
    # Run with stdout suppressed so the test does not pollute pytest output.
    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("add a comment to foo.py", ns)
    assert rc == 0
    runs_root = tmp_path / ".local-codex-lite" / "runs"
    runs = sorted(runs_root.iterdir())
    assert len(runs) == 1
    run = runs[0]
    assert (run / "plan.json").exists()
    assert (run / "result.json").exists()
    assert json.loads((run / "result.json").read_text())["dry_run"] is True


def test_dry_run_without_json_still_works(tmp_path: Path, monkeypatch, capsys) -> None:
    """The new --json flag must not regress the default rich dry-run output."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("local_codex_lite.planner.OpenAICompatibleClient", _StubLLM)
    monkeypatch.setattr("local_codex_lite.runner.load_config", lambda root: AgentConfig())

    ns = argparse.Namespace(
        dry_run=True, apply=False, execute=False, assume_clarification=False,
        evidence_file=[], evidence_stdin=False,
        max_patch_attempts=None, json_output=False,
    )
    rc = runner.run_task("add a comment to foo.py", ns)
    out = capsys.readouterr().out
    assert rc == 0
    # In rich mode the plan summary appears in the captured stdout.
    assert "stub-plan" in out
    # And the whole thing is NOT valid JSON (rich noise around it).
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)

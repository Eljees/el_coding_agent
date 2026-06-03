"""Targeted runner coverage: the run_task --json redirect wrapper and the
early-exit error branch of _run_task_body (unknown --profile).

The full end-to-end workflow is exercised elsewhere; these lock down the cheap
control-flow paths that were uncovered.
"""

from __future__ import annotations

import argparse

from local_codex_lite import runner
from local_codex_lite.config import UnknownProfileError


def test_run_task_delegates_plain_mode(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(
        runner,
        "_run_task_body",
        lambda task, args, **kw: seen.setdefault("json", kw["json_mode"]) or 7,
    )
    rc = runner.run_task("t", argparse.Namespace(json_output=False))
    assert rc == 7 and seen["json"] is False


def test_run_task_delegates_json_mode(monkeypatch) -> None:
    captured = {}

    def fake_body(task, args, *, json_mode=False, real_stdout=None):
        captured["json_mode"] = json_mode
        return 0

    monkeypatch.setattr(runner, "_run_task_body", fake_body)
    rc = runner.run_task("t", argparse.Namespace(json_output=True))
    assert rc == 0 and captured["json_mode"] is True


def test_run_task_body_unknown_profile_returns_1(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(runner, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "resolve_task_workspace", lambda base, task: base)
    monkeypatch.setattr(runner, "load_config", lambda root: object())

    def boom(cfg, profile):
        raise UnknownProfileError("no such profile: ghost")

    monkeypatch.setattr(runner, "apply_profile", boom)
    rc = runner._run_task_body("t", argparse.Namespace(profile="ghost"))
    assert rc == 1
    assert "ghost" in capsys.readouterr().out

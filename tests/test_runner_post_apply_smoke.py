"""Runner coverage for the post-apply smoke gate.

The patch parses (AST gate passes) but the touched entrypoint script crashes
on startup; with smoke enabled the runner must restore backups and feed the
captured traceback into the bounded repair loop -- the model gets its OWN
runtime error back.  Mirrors the structure of test_runner_repair_loop.py:
real throwaway git repo, planner seams stubbed directly on the runner module.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
from pathlib import Path

from local_codex_lite import runner
from local_codex_lite.config import AgentConfig

_PLAN = {"summary": "edit foo", "needs_clarification": False}

_ORIGINAL = "if __name__ == \"__main__\":\n    print('hi')\n"


def _runtime_broken_diff(n: int) -> str:
    """Valid Python after apply, but crashes on startup (missing module).
    Distinct per *n* so successive repair attempts are never byte-identical."""
    return (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,3 @@\n"
        f"+import nonexistent_module_el_{n}\n"
        ' if __name__ == "__main__":\n'
        "     print('hi')\n"
    )


_DIFF_FIX = (
    "diff --git a/foo.py b/foo.py\n"
    "--- a/foo.py\n"
    "+++ b/foo.py\n"
    "@@ -1,2 +1,3 @@\n"
    "+# fixed by repair\n"
    ' if __name__ == "__main__":\n'
    "     print('hi')\n"
)


def _init_git_repo(path: Path, content: str = _ORIGINAL) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "foo.py").write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "foo.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        dry_run=False,
        apply=True,
        execute=False,
        smoke=False,
        assume_clarification=False,
        evidence_file=[],
        evidence_stdin=False,
        max_patch_attempts=None,
        json_output=False,
        profile=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _stub_planner_seams(monkeypatch, first_patch: str, repair_patches: list[str]) -> dict:
    """Stub make_plan/make_patch/repair/suggest on the runner module so the
    test isolates the runner's smoke-gate logic from the planner internals."""
    calls = {"repairs": 0}
    monkeypatch.setattr(runner, "make_plan", lambda *a, **k: dict(_PLAN))
    monkeypatch.setattr(runner, "make_patch", lambda *a, **k: first_patch)

    def fake_repair(*a, **k):
        index = min(calls["repairs"], len(repair_patches) - 1)
        calls["repairs"] += 1
        return repair_patches[index]

    monkeypatch.setattr(runner, "repair_patch_with_error", fake_repair)
    monkeypatch.setattr(runner, "suggest_commands", lambda *a, **k: {"commands": []})
    return calls


def _runs(tmp_path: Path) -> list[Path]:
    return list((tmp_path / ".local-codex-lite" / "runs").iterdir())


def test_smoke_gate_restores_then_repairs(tmp_path, monkeypatch) -> None:
    """Runtime-broken patch applies and parses, smoke fails, backups are
    restored, and the repair attempt (driven by the traceback) succeeds."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_config", lambda root: AgentConfig())
    calls = _stub_planner_seams(monkeypatch, _runtime_broken_diff(1), [_DIFF_FIX])

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns(smoke=True, max_patch_attempts=4))

    assert rc == 0
    assert calls["repairs"] == 1
    text = (tmp_path / "foo.py").read_text(encoding="utf-8")
    assert "# fixed by repair" in text
    assert "nonexistent_module" not in text  # broken attempt was rolled back
    run_dir = _runs(tmp_path)[0]
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result["patch_attempts"] == 2
    assert result["applied"] is True
    # Evidence trail: the failed smoke attempt and the repair hand-off.
    smoke_issue = json.loads((run_dir / "smoke_issue.json").read_text(encoding="utf-8"))
    assert smoke_issue["patch_error"]["code"] == "post_apply_runtime"
    assert "nonexistent_module_el_1" in smoke_issue["detail"]
    assert (run_dir / "smoke.json").exists()


def test_smoke_gate_exhausted_returns_1_and_restores(tmp_path, monkeypatch) -> None:
    """Every attempt crashes at runtime; once max_patch_attempts is spent the
    run fails with stage post_apply_smoke and foo.py is back to pristine."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_config", lambda root: AgentConfig())
    _stub_planner_seams(
        monkeypatch, _runtime_broken_diff(1), [_runtime_broken_diff(2), _runtime_broken_diff(3)]
    )

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns(smoke=True, max_patch_attempts=2))

    assert rc == 1
    assert (tmp_path / "foo.py").read_text(encoding="utf-8") == _ORIGINAL
    run_dir = _runs(tmp_path)[0]
    failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "post_apply_smoke"
    assert failure["patch_error"]["code"] == "post_apply_runtime"
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result["applied"] is False


def test_smoke_gate_off_by_default(tmp_path, monkeypatch) -> None:
    """Without --smoke (and with the conservative config default) a runtime-
    broken patch is still accepted: smoke executes generated code, so the
    project never runs it unless explicitly asked."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_config", lambda root: AgentConfig())
    _stub_planner_seams(monkeypatch, _runtime_broken_diff(1), [_DIFF_FIX])

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns())

    assert rc == 0
    assert "nonexistent_module_el_1" in (tmp_path / "foo.py").read_text(encoding="utf-8")
    assert not (_runs(tmp_path)[0] / "smoke.json").exists()


def test_smoke_enabled_via_config_default(tmp_path, monkeypatch) -> None:
    """safety.smoke_run_default=true enables the gate without the CLI flag;
    a clean entrypoint passes and the smoke evidence is recorded."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = AgentConfig.model_validate({"safety": {"smoke_run_default": True}})
    monkeypatch.setattr(runner, "load_config", lambda root: cfg)
    _stub_planner_seams(monkeypatch, _DIFF_FIX, [_DIFF_FIX])

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns())

    assert rc == 0
    run_dir = _runs(tmp_path)[0]
    smoke = json.loads((run_dir / "smoke.json").read_text(encoding="utf-8"))
    assert len(smoke) == 1
    assert smoke[0]["ok"] is True
    assert smoke[0]["returncode"] == 0


def test_smoke_enabled_but_no_entrypoints(tmp_path, monkeypatch) -> None:
    """--smoke on a patch that touches only library files (no __main__ guard)
    runs nothing and records nothing -- there is no entrypoint to prove."""
    _init_git_repo(tmp_path, content="print('hi')\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_config", lambda root: AgentConfig())
    library_diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1,2 @@\n"
        "+# added by agent\n"
        " print('hi')\n"
    )
    _stub_planner_seams(monkeypatch, library_diff, [library_diff])

    with contextlib.redirect_stdout(io.StringIO()):
        rc = runner.run_task("edit foo.py", _ns(smoke=True))

    assert rc == 0
    assert not (_runs(tmp_path)[0] / "smoke.json").exists()

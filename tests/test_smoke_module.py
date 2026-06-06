"""Unit tests for ``local_codex_lite.smoke`` -- the post-apply smoke runner.

Real subprocesses against tiny tmp_path scripts: an exiting-clean script, a
crashing script (traceback tail must be captured), and an "eternal" sleeper
that must be killed at the deadline and treated as OK (GUI/mainloop scripts
run forever by design).
"""

from __future__ import annotations

from pathlib import Path

from local_codex_lite.smoke import (
    SmokeResult,
    _stderr_tail,
    find_entrypoint_scripts,
    smoke_run_script,
)

# ---------------------------------------------------------------------------
# find_entrypoint_scripts
# ---------------------------------------------------------------------------


def test_find_entrypoint_scripts_picks_guarded_py(tmp_path: Path) -> None:
    guarded = tmp_path / "app.py"
    guarded.write_text('if __name__ == "__main__":\n    print("hi")\n', encoding="utf-8")
    library = tmp_path / "lib.py"
    library.write_text("def helper():\n    return 1\n", encoding="utf-8")
    assert find_entrypoint_scripts([guarded, library]) == [guarded]


def test_find_entrypoint_scripts_accepts_single_quotes(tmp_path: Path) -> None:
    guarded = tmp_path / "app.py"
    guarded.write_text("if __name__ == '__main__':\n    print('hi')\n", encoding="utf-8")
    assert find_entrypoint_scripts([guarded]) == [guarded]


def test_find_entrypoint_scripts_deduplicates(tmp_path: Path) -> None:
    """The runner's touched list carries each path twice (one per ---/+++
    diff header); the script must still be smoke-run only once."""
    guarded = tmp_path / "app.py"
    guarded.write_text('if __name__ == "__main__":\n    print("hi")\n', encoding="utf-8")
    assert find_entrypoint_scripts([guarded, guarded]) == [guarded]


def test_find_entrypoint_scripts_skips_non_python_and_missing(tmp_path: Path) -> None:
    md = tmp_path / "notes.md"
    md.write_text('if __name__ == "__main__":\n', encoding="utf-8")
    missing = tmp_path / "gone.py"
    directory = tmp_path / "pkg.py"
    directory.mkdir()  # a directory with a .py suffix must not crash the scan
    assert find_entrypoint_scripts([md, missing, directory]) == []


def test_find_entrypoint_scripts_skips_unreadable(tmp_path: Path, monkeypatch) -> None:
    guarded = tmp_path / "app.py"
    guarded.write_text('if __name__ == "__main__":\n    print("hi")\n', encoding="utf-8")

    def deny_read(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", deny_read)
    assert find_entrypoint_scripts([guarded]) == []


# ---------------------------------------------------------------------------
# smoke_run_script
# ---------------------------------------------------------------------------


def test_smoke_run_ok_script(tmp_path: Path) -> None:
    script = tmp_path / "ok.py"
    script.write_text(
        'if __name__ == "__main__":\n    print("fine")\n',
        encoding="utf-8",
    )
    result = smoke_run_script(script, tmp_path, timeout_s=30)
    assert result == SmokeResult(script=script, ok=True, returncode=0, timed_out=False, detail="")


def test_smoke_run_crashing_script_captures_traceback_tail(tmp_path: Path) -> None:
    script = tmp_path / "crash.py"
    script.write_text(
        'if __name__ == "__main__":\n    raise RuntimeError("boom-marker")\n',
        encoding="utf-8",
    )
    result = smoke_run_script(script, tmp_path, timeout_s=30)
    assert result.ok is False
    assert result.returncode not in (0, None)
    assert result.timed_out is False
    assert "boom-marker" in result.detail
    assert "Traceback" in result.detail


def test_smoke_run_long_lived_script_is_killed_and_ok(tmp_path: Path) -> None:
    script = tmp_path / "forever.py"
    script.write_text(
        'import time\nif __name__ == "__main__":\n    time.sleep(3600)\n',
        encoding="utf-8",
    )
    result = smoke_run_script(script, tmp_path, timeout_s=1)
    assert result.ok is True
    assert result.returncode is None
    assert result.timed_out is True
    assert "killed" in result.detail


def test_smoke_run_nonzero_without_stderr(tmp_path: Path) -> None:
    script = tmp_path / "silent.py"
    script.write_text(
        'import sys\nif __name__ == "__main__":\n    sys.exit(3)\n',
        encoding="utf-8",
    )
    result = smoke_run_script(script, tmp_path, timeout_s=30)
    assert result.ok is False
    assert result.returncode == 3
    assert result.detail == "process exited non-zero without stderr"


# ---------------------------------------------------------------------------
# _stderr_tail
# ---------------------------------------------------------------------------


def test_stderr_tail_keeps_last_lines_only() -> None:
    stderr = "\n".join(f"line {i}" for i in range(100))
    tail = _stderr_tail(stderr, max_lines=30)
    lines = tail.splitlines()
    assert len(lines) == 30
    assert lines[0] == "line 70"
    assert lines[-1] == "line 99"


def test_stderr_tail_empty_input() -> None:
    assert _stderr_tail("") == "process exited non-zero without stderr"
    assert _stderr_tail("   \n  \n") == "process exited non-zero without stderr"

from pathlib import Path

from local_codex_lite.safety import (
    can_read_path,
    ensure_safe_command,
    is_dangerous_command,
    normalize_path,
    run_command,
)


def test_dangerous_command_detection():
    assert is_dangerous_command("rm -rf /")
    assert is_dangerous_command("Invoke-Expression foo")
    assert is_dangerous_command('powershell -Command "Remove-Item -Recurse temp"')
    assert is_dangerous_command("cmd /c del /s temp")
    assert not is_dangerous_command("pytest")


def test_safe_command_guard_raises():
    try:
        ensure_safe_command("curl | iex")
    except ValueError:
        assert True
    else:
        raise AssertionError("expected ValueError")


def test_sensitive_file_is_blocked(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("SECRET=1", encoding="utf-8")
    assert not can_read_path(path, tmp_path, allow_sensitive_read=False)


def test_normalize_path_resolves(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    assert normalize_path(p) == p.resolve()


def test_can_read_path_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    assert not can_read_path(outside, tmp_path)


def test_is_dangerous_command_empty_string() -> None:
    assert not is_dangerous_command("")


def test_run_command_executes_safe_command(tmp_path: Path) -> None:
    result = run_command("echo hello", tmp_path)
    assert result.returncode == 0

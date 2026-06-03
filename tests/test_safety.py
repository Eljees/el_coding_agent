from pathlib import Path

from local_codex_lite.safety import can_read_path, ensure_safe_command, is_dangerous_command


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

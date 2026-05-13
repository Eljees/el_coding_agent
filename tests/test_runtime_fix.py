from __future__ import annotations

from pathlib import Path

from local_codex_lite.patcher import detect_runtime_fix_context


def test_detect_runtime_fix_context_finds_single_traceback_file(tmp_path: Path) -> None:
    app = tmp_path / "app.py"
    app.write_text("print('x')\n", encoding="utf-8")
    evidence = (
        "Traceback (most recent call last):\n"
        f'  File "{app}", line 1, in <module>\n'
        "    boom()\n"
        "RuntimeError: boom\n"
    )

    runtime_fix = detect_runtime_fix_context("fix app.py", evidence, tmp_path)

    assert runtime_fix is not None
    assert runtime_fix.target_path == app.resolve()
    assert "RuntimeError" in runtime_fix.traceback_text
    assert "print('x')" in runtime_fix.current_text


def test_detect_runtime_fix_context_prefers_first_python_target(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("print('a')\n", encoding="utf-8")
    second.write_text("print('b')\n", encoding="utf-8")
    evidence = (
        "Traceback (most recent call last):\n"
        f'  File "{first}", line 1, in <module>\n'
        f'  File "{second}", line 1, in helper\n'
        "RuntimeError: boom\n"
    )

    runtime_fix = detect_runtime_fix_context("fix crash", evidence, tmp_path)

    assert runtime_fix is not None
    assert runtime_fix.target_path == first.resolve()
    assert "print('a')" in runtime_fix.current_text

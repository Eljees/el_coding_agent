from __future__ import annotations

from pathlib import Path

from local_codex_lite.targeting import detect_task_target


def test_detect_task_target_for_create_file(tmp_path: Path) -> None:
    target = detect_task_target("Create a new Python file named calculator.py", tmp_path)

    assert target is not None
    assert target.path == "calculator.py"
    assert target.mode == "create"
    assert target.exists is False


def test_detect_task_target_for_existing_file(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('x')", encoding="utf-8")

    target = detect_task_target("Fix src/app.py after test failure", tmp_path)

    assert target is not None
    assert target.path == "src/app.py"
    assert target.mode == "update"
    assert target.exists is True

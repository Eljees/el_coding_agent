from __future__ import annotations

from pathlib import Path

from local_codex_lite.config import load_config, save_config
from local_codex_lite.project_workspace import (
    PROJECT_WORKSPACE_DIR,
    create_project_workspace,
    resolve_task_workspace,
    should_use_project_workspace,
    slugify_task,
)


def test_slugify_task_uses_ascii_fallback() -> None:
    assert slugify_task("Create GUI calculator") == "create-gui-calculator"
    assert slugify_task("Сделай GUI калькулятор") == "gui"


def test_should_use_project_workspace_detects_generation_tasks() -> None:
    assert should_use_project_workspace("Create a Tkinter calculator app") is True
    assert should_use_project_workspace("Сделай GUI калькулятор") is True
    assert should_use_project_workspace("Fix bug in patcher.py") is False
    assert should_use_project_workspace("сравни left.json и right.json") is False


def test_create_project_workspace_copies_base_config(tmp_path: Path) -> None:
    base_root = tmp_path / "agent"
    base_root.mkdir()
    cfg = load_config(base_root)
    cfg.llm.model = "custom-local-model"
    save_config(base_root, cfg)

    project_root = create_project_workspace(base_root, "Create GUI calculator app")

    assert project_root.parent == base_root / PROJECT_WORKSPACE_DIR
    assert project_root.exists()
    assert load_config(project_root).llm.model == "custom-local-model"


def test_resolve_task_workspace_reuses_normal_workspace_for_fix_tasks(tmp_path: Path) -> None:
    base_root = tmp_path / "agent"
    base_root.mkdir()

    resolved = resolve_task_workspace(base_root, "Fix bug in patcher.py")

    assert resolved == base_root

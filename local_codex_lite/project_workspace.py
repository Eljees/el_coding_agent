from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import load_config, save_config

PROJECT_WORKSPACE_DIR = "generated_projects"
PROJECT_TASK_KEYWORDS = (
    "create",
    "build",
    "generate",
    "new project",
    "new app",
    "new tool",
    "calculator",
    "gui",
    "desktop app",
    "desktop tool",
    "tkinter",
    "site",
    "game",
    "client",
    "window",
    "создай",
    "сделай",
    "собери",
    "приложение",
    "проект",
    "калькулятор",
    "окно",
    "интерфейс",
    "гуй",
)
NON_PROJECT_HINTS = (
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    "fix",
    "bug",
    "patch",
    "readme",
    "logs",
    "json compare",
    "compare json",
    "сравни",
    "исправь",
    "лог",
)


def slugify_task(task: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")
    if not slug:
        return "task"
    return slug[:limit].strip("-") or "task"


def is_generated_project_workspace(path: Path) -> bool:
    return PROJECT_WORKSPACE_DIR in path.parts


def should_use_project_workspace(task: str) -> bool:
    lower = task.lower()
    if any(hint in lower for hint in NON_PROJECT_HINTS):
        return False
    return any(keyword in lower for keyword in PROJECT_TASK_KEYWORDS)


def create_project_workspace(base_root: Path, task: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_root = base_root / PROJECT_WORKSPACE_DIR / f"{stamp}_{slugify_task(task)}"
    project_root.mkdir(parents=True, exist_ok=True)
    save_config(project_root, load_config(base_root))
    return project_root


def resolve_task_workspace(base_root: Path, task: str) -> Path:
    if is_generated_project_workspace(base_root):
        return base_root
    if not should_use_project_workspace(task):
        return base_root
    return create_project_workspace(base_root, task)

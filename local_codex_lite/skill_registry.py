from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_BLOCKED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".local-codex-lite",
}


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    path: Path
    summary: str


def discover_skills(root: Path) -> list[SkillDefinition]:
    root = root.resolve()
    skills: list[SkillDefinition] = []
    for path in sorted(root.rglob("SKILL.md")):
        rel_parts = path.relative_to(root).parts
        if any(part in _BLOCKED_DIRS for part in rel_parts[:-1]):
            continue
        skills.append(_read_skill(path))
    return skills


def skill_brief_lines(skills: list[SkillDefinition]) -> list[str]:
    if not skills:
        return ["No local SKILL.md files found"]
    return [f"{item.name} - {item.summary}" for item in skills]


def _read_skill(path: Path) -> SkillDefinition:
    text = path.read_text(encoding="utf-8", errors="replace")
    name = _first_heading(text) or path.parent.name
    summary = _first_body_line(text) or "Local skill instructions"
    return SkillDefinition(name=name, path=path, summary=summary)


def _first_heading(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _first_body_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line[:160]
    return ""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .path_filters import path_has_blocked_dir


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
        if path_has_blocked_dir(rel_parts[:-1]):
            continue
        skills.append(_read_skill(path))
    return skills


def skill_brief_lines(skills: list[SkillDefinition]) -> list[str]:
    if not skills:
        return ["No local SKILL.md files found"]
    return [f"{item.name} - {item.summary}" for item in skills]


def _read_skill(path: Path) -> SkillDefinition:
    text = path.read_text(encoding="utf-8", errors="replace")
    metadata, body = _split_frontmatter(text)
    name = str(metadata.get("name") or _first_heading(body) or path.parent.name).strip()
    summary = str(metadata.get("description") or _first_body_line(body) or "Local skill instructions").strip()
    return SkillDefinition(name=name, path=path, summary=summary)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    end_index = None
    for index in range(1, len(lines)):
        line = lines[index].strip()
        if line == "---":
            end_index = index
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    if end_index is None:
        return {}, text
    body = "\n".join(lines[end_index + 1 :]).lstrip()
    return metadata, body


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

from __future__ import annotations

from pathlib import Path

from local_codex_lite.skill_registry import discover_skills, skill_brief_lines
from local_codex_lite.tool_registry import default_tools


def test_default_tools_include_guarded_shell_runner() -> None:
    tools = {tool.name: tool for tool in default_tools()}

    assert "shell.run" in tools
    assert "evidence.artifacts.inspect" in tools
    assert "evidence.cve_scan" in tools
    assert tools["shell.run"].requires_exec is True
    assert tools["shell.run"].safety_level == "guarded"
    assert tools["evidence.artifacts.inspect"].requires_exec is False
    assert tools["evidence.cve_scan"].requires_exec is False
    assert tools["evidence.cve_scan"].schema["properties"]["min_severity"]["default"] == "HIGH"


def test_discover_skills_reads_local_skill_md(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("# Demo Skill\n\nUse for demo tasks.", encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "Demo Skill"
    assert skills[0].path == skill_path
    assert skill_brief_lines(skills) == ["Demo Skill - Use for demo tasks."]


def test_discover_skills_prefers_frontmatter_name_and_description(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\nname: demo-frontmatter\ndescription: Use for frontmatter-aware tasks.\n---\n\n# Ignored Heading\n\nBody.\n",
        encoding="utf-8",
    )

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "demo-frontmatter"
    assert skills[0].summary == "Use for frontmatter-aware tasks."


def test_discover_skills_skips_blocked_dirs(tmp_path: Path) -> None:
    blocked = tmp_path / ".git" / "hooks"
    blocked.mkdir(parents=True)
    (blocked / "SKILL.md").write_text("# Should be skipped", encoding="utf-8")

    assert discover_skills(tmp_path) == []


def test_skill_brief_lines_empty() -> None:
    assert skill_brief_lines([]) == ["No local SKILL.md files found"]


def test_discover_skills_frontmatter_without_closing_fence(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\n# Heading\n\nBody text.", encoding="utf-8"
    )

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "Heading"


def test_discover_skills_frontmatter_line_without_colon(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "partial"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: partial\nthis line has no colon\n---\n\nBody.", encoding="utf-8"
    )

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "partial"


def test_first_heading_fallback_to_dir_name(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "myskill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("No heading here, just plain text.", encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "myskill"


def test_first_body_line_skips_headings(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "onlyheadings"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Only headings\n## Another heading", encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert skills[0].summary == "Local skill instructions"

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

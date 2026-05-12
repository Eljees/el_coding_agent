from __future__ import annotations

from pathlib import Path

from local_codex_lite import cli_evidence, ui


def test_cve_min_severity_for_task_defaults_to_high() -> None:
    assert ui.cve_min_severity_for_task(r"проверь на cve артефакт D:\artifacts\demo.rpm") == "HIGH"


def test_cve_min_severity_for_task_detects_medium_request() -> None:
    assert ui.cve_min_severity_for_task("сделай полный cve отчёт включая medium") == "MEDIUM"
    assert ui.cve_min_severity_for_task("нужен расширенный отчёт по cve") == "MEDIUM"


def test_format_duration_renders_mm_ss() -> None:
    assert ui.format_duration(5) == "00:05"
    assert ui.format_duration(125) == "02:05"


def test_resolve_cve_skill_script_prefers_repo_root() -> None:
    root = Path(__file__).resolve().parents[1]

    path = cli_evidence.resolve_cve_skill_script(root)

    assert path == root / "skills" / "cve-bin-tool" / "run_cve_scan.py"
    assert path.exists()

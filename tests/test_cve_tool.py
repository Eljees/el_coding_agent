from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from local_codex_lite import cli, cli_evidence


def _load_cve_runner():
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "skills" / "cve-bin-tool" / "run_cve_scan.py"
    spec = importlib.util.spec_from_file_location("cve_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cve_runner_normalize_format_tokens_default() -> None:
    runner = _load_cve_runner()

    assert runner.normalize_format_tokens(None) == ["json", "md", "high-critical-md"]


def test_cve_runner_normalize_format_tokens_accepts_aliases() -> None:
    runner = _load_cve_runner()

    assert runner.normalize_format_tokens("md,high_critical_md,csv") == [
        "json",
        "md",
        "high-critical-md",
        "csv",
    ]


def test_cve_runner_renders_high_critical_report(tmp_path: Path) -> None:
    runner = _load_cve_runner()
    artifact = tmp_path / "demo.rpm"
    artifact.write_bytes(b"binary payload")
    summary = {
        "severity_counts": {"CRITICAL": 1, "HIGH": 1},
    }
    findings = [
        {
            "cve": "CVE-2025-0001",
            "severity": "CRITICAL",
            "score": 9.8,
            "vendor": "sqlite",
            "product": "sqlite",
            "version": "3.41.2",
            "source": "NVD",
        },
        {
            "cve": "CVE-2024-0002",
            "severity": "HIGH",
            "score": 7.5,
            "vendor": "gnu",
            "product": "gcc",
            "version": "7.3.1",
            "source": "NVD",
        },
    ]

    report = runner.render_high_critical_report(
        input_root=artifact,
        scan_summary=summary,
        findings=findings,
    )

    assert "# demo.rpm: high/critical findings" in report
    assert "SHA256:" in report
    assert "CVE-2025-0001" in report
    assert "CVE-2024-0002" in report
    assert "`cve-bin-tool`: `CRITICAL=1`, `HIGH=1`" in report


def test_cli_parser_accepts_cve_status_action() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["evidence", "cve-scan", "status"])

    assert args.evidence_command == "cve-scan"
    assert args.action_or_input == "status"
    assert args.input_root is None


def test_cli_parser_accepts_legacy_cve_scan_path() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["evidence", "cve-scan", r"D:\artifacts", "--format", "json,md"])

    assert args.evidence_command == "cve-scan"
    assert args.action_or_input == r"D:\artifacts"
    assert args.input_root is None
    assert args.format == "json,md"


def test_cmd_evidence_cve_scan_builds_status_command(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd, check=False):  # noqa: ANN001
        captured.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_evidence.subprocess, "run", fake_run)
    args = SimpleNamespace(
        action_or_input="status",
        input_root=None,
        extract_to=None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=False,
        min_severity="HIGH",
        format="json,md,high-critical-md",
    )

    code = cli_evidence.cmd_evidence_cve_scan(args)

    assert code == 0
    assert captured
    assert captured[0][-1] == "status"


def test_cmd_evidence_cve_scan_builds_scan_command(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd, check=False):  # noqa: ANN001
        captured.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_evidence.subprocess, "run", fake_run)
    args = SimpleNamespace(
        action_or_input=r"D:\artifacts",
        input_root=None,
        extract_to=r"D:\unpacked",
        output_dir=r"D:\evidence",
        install=True,
        update_db=True,
        skip_unpack=True,
        offline=True,
        min_severity="HIGH",
        format="json,md,high-critical-md",
    )

    code = cli_evidence.cmd_evidence_cve_scan(args)

    assert code == 0
    assert captured
    cmd = captured[0]
    assert "scan" in cmd
    assert r"D:\artifacts" in cmd
    assert "--extract-to" in cmd
    assert "--output-dir" in cmd
    assert "--install" in cmd
    assert "--update-db" in cmd
    assert "--skip-unpack" in cmd
    assert "--offline" in cmd
    assert "--format" in cmd

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

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
    case_dir = tmp_path / "CYBERSEC-11195"
    case_dir.mkdir()
    artifact = case_dir / "demo.rpm"
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

    assert "# CYBERSEC-11195: high/critical findings" in report
    assert "- `demo.rpm`" in report
    assert "SHA256:" in report
    assert "CVE-2025-0001" in report
    assert "CVE-2024-0002" in report
    assert "`cve-bin-tool`: `CRITICAL=1`, `HIGH=1`" in report


def test_cve_runner_infers_case_id_from_path(tmp_path: Path) -> None:
    runner = _load_cve_runner()
    artifact = tmp_path / "CYBERSEC-54321" / "nested" / "demo.rpm"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"binary payload")

    assert runner.infer_case_id(artifact) == "CYBERSEC-54321"


def test_cve_runner_classifies_partial_when_unpack_incomplete(tmp_path: Path) -> None:
    runner = _load_cve_runner()
    raw = tmp_path / "cve_raw.json"
    raw.write_text("[]", encoding="utf-8")

    status, error_code, evidence_complete = runner.classify_status(
        unpack_summary={"archives_failed": 1, "archives_blocked": 0, "missing_tool": 0},
        scan_summary={"scan_exit_code": 1},
        raw_json_path=str(raw),
    )

    assert status == "partial"
    assert error_code == "artifact_unpack_incomplete"
    assert evidence_complete is False


def test_cve_runner_classifies_failed_without_raw_json(tmp_path: Path) -> None:
    runner = _load_cve_runner()

    status, error_code, evidence_complete = runner.classify_status(
        unpack_summary={"archives_failed": 0, "archives_blocked": 0, "missing_tool": 0},
        scan_summary={"scan_exit_code": 0},
        raw_json_path=str(tmp_path / "missing.json"),
    )

    assert status == "failed"
    assert error_code == "scan_no_raw_json"
    assert evidence_complete is False


def test_cve_runner_scan_argv_defaults_to_update_never(tmp_path: Path, monkeypatch) -> None:
    runner = _load_cve_runner()
    captured: list[list[str]] = []
    captured_cwds: list[Path | None] = []
    raw = tmp_path / "cve_raw.json"
    raw.write_text("[]", encoding="utf-8")

    def fake_run(argv, capture_output=False, text=False, check=False, timeout=0, cwd=None):
        captured.append(argv)
        captured_cwds.append(cwd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    findings, summary, raw_path = runner.run_scan(
        runner.ToolCommand(argv=["cve-bin-tool"], mode="executable", display="cve-bin-tool"),
        tmp_path,
        tmp_path,
        severity="HIGH",
        offline=False,
    )

    assert findings == []
    assert summary["scan_exit_code"] == 0
    assert raw_path.endswith("cve_raw.json")
    assert captured
    assert captured_cwds == [tmp_path]
    assert "--update" in captured[0]
    update_index = captured[0].index("--update")
    assert captured[0][update_index + 1] == "never"


def test_cve_runner_fallback_search_stays_inside_output_dir(tmp_path: Path, monkeypatch) -> None:
    runner = _load_cve_runner()
    scan_dir = tmp_path / "scan"
    output_dir = tmp_path / "evidence"
    scan_dir.mkdir()
    output_dir.mkdir()

    stray = tmp_path / "output.cve-bin-tool.2026-05-13.09-00-00.json"
    stray.write_text(
        json.dumps([{"cve_number": "CVE-2024-9999", "severity": "CRITICAL", "product": "wrong"}]),
        encoding="utf-8",
    )
    now = time.time()
    os.utime(stray, (now, now))

    def fake_run(argv, capture_output=False, text=False, check=False, timeout=0, cwd=None):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    findings, summary, raw_path = runner.run_scan(
        runner.ToolCommand(argv=["cve-bin-tool"], mode="executable", display="cve-bin-tool"),
        scan_dir,
        output_dir,
        severity="HIGH",
        offline=False,
    )

    assert findings == []
    assert summary["total_findings"] == 0
    assert Path(raw_path) == output_dir / "cve_raw.json"


def test_cve_runner_update_db_uses_streaming_command(monkeypatch) -> None:
    runner = _load_cve_runner()
    captured: list[list[str]] = []

    def fake_stream(argv, *, timeout):
        captured.append(argv)
        assert timeout == 1800
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    class FakeTempDir:
        def __enter__(self):
            return r"C:\temp\cve-update"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(runner, "run_streaming_command", fake_stream)
    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", lambda prefix="": FakeTempDir())

    payload = runner.update_cve_db(
        runner.ToolCommand(argv=["cve-bin-tool"], mode="executable", display="cve-bin-tool"),
        offline=False,
    )

    assert payload["status"] == "ok"
    assert captured
    assert "--update" in captured[0]
    assert "now" in captured[0]
    assert captured[0][-1] == r"C:\temp\cve-update"
    # Build the expected path with os.path.join so the assertion checks the
    # join logic, not the platform-specific separator (\\ on Windows, / on POSIX).
    expected_output = os.path.join(r"C:\temp\cve-update", "update-db.json")
    assert captured[0][captured[0].index("--output-file") + 1] == expected_output


def test_cve_runner_merge_unpack_summaries_accumulates_counts() -> None:
    runner = _load_cve_runner()

    merged = runner._merge_unpack_summaries(
        {"archives_total": 1, "files_extracted": 1, "extraction_root": r"D:\out"},
        {
            "archives_total": 2,
            "files_extracted": 5,
            "missing_tool": 1,
            "extraction_root": r"D:\other",
        },
    )

    assert merged["archives_total"] == 3
    assert merged["files_extracted"] == 6
    assert merged["missing_tool"] == 1
    assert merged["extraction_root"] == r"D:\out"


def test_cve_runner_expand_nested_archives_processes_new_archives_only(tmp_path: Path) -> None:
    runner = _load_cve_runner()
    outer = tmp_path / "outer.cpio"
    inner = tmp_path / "nested" / "inner.cpio"
    inner.parent.mkdir()
    outer.write_text("outer", encoding="utf-8")
    inner.write_text("inner", encoding="utf-8")
    calls: list[Path] = []

    def fake_archive_format(path: Path) -> str:
        return "cpio" if path.suffix == ".cpio" else "unsupported"

    class FakeResult:
        def __init__(self, count: int) -> None:
            self.summary = {"archives_total": 1, "files_extracted": count}

    def fake_inspect_artifacts(path: Path, output_root: Path, **kwargs):
        calls.append(path)
        return FakeResult(1)

    summary = runner._expand_nested_archives(tmp_path, fake_archive_format, fake_inspect_artifacts)

    assert summary["archives_total"] == 2
    assert len(calls) == 2
    assert {item.name for item in calls} == {"outer.cpio", "inner.cpio"}


def test_cve_runner_unpack_archives_passes_extract_target(monkeypatch, tmp_path: Path) -> None:
    runner = _load_cve_runner()
    source = tmp_path / "demo.rpm"
    source.write_text("rpm", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeResult:
        summary: ClassVar[dict] = {"archives_total": 1, "files_extracted": 1}
        extraction_root = str(tmp_path / "out")

    def fake_inspect_artifacts(source_root, output_root, **kwargs):
        captured["source_root"] = source_root
        captured["output_root"] = output_root
        captured["kwargs"] = kwargs
        return FakeResult()

    monkeypatch.setitem(
        sys.modules,
        "local_codex_lite.artifact_unpack",
        SimpleNamespace(
            archive_format=lambda path: "unsupported",
            inspect_artifacts=fake_inspect_artifacts,
        ),
    )
    monkeypatch.setattr(runner, "_expand_nested_archives", lambda *args, **kwargs: {})

    summary = runner.unpack_archives(source, tmp_path / "out")

    assert summary["archives_total"] == 1
    assert captured["source_root"] == source
    assert captured["output_root"] == tmp_path / "out"
    assert captured["kwargs"]["extract_to"] == tmp_path / "out"


def test_cve_runner_find_fallback_output_json_prefers_recent_file(tmp_path: Path) -> None:
    runner = _load_cve_runner()
    old_file = tmp_path / "output.cve-bin-tool.2026-05-12.22-00-00.json"
    new_file = tmp_path / "output.cve-bin-tool.2026-05-12.22-10-00.json"
    old_file.write_text("[]", encoding="utf-8")
    new_file.write_text("[]", encoding="utf-8")

    old_time = time.time() - 100
    new_time = time.time()
    os.utime(old_file, (old_time, old_time))
    os.utime(new_file, (new_time, new_time))

    found = runner.find_fallback_output_json(tmp_path, started_after=new_time - 1)

    assert found == new_file


def test_cve_runner_load_findings_supports_json2_structure(tmp_path: Path) -> None:
    runner = _load_cve_runner()
    raw = tmp_path / "cve_export.json2"
    raw.write_text(
        json.dumps(
            {
                "vulnerabilities": {
                    "report": [
                        {
                            "datasource": "NVD",
                            "entries": [
                                {
                                    "cve_number": "CVE-2024-0001",
                                    "severity": "HIGH",
                                    "score": "7.5",
                                    "vendor": "gnu",
                                    "product": "gcc",
                                    "version": "8.5.0",
                                    "source": "NVD",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    findings = runner.load_findings(raw)

    assert len(findings) == 1
    assert findings[0]["cve"] == "CVE-2024-0001"
    assert findings[0]["severity"] == "HIGH"
    assert findings[0]["product"] == "gcc"


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


def test_cli_parser_defaults_cve_min_severity_to_high() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["evidence", "cve-scan", r"D:\artifacts"])

    assert args.min_severity == "HIGH"


def test_cmd_evidence_cve_scan_builds_status_command(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd, check=False, capture_output=False, text=False, encoding=None, errors=None):
        captured.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

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

    def fake_run(cmd, check=False, capture_output=False, text=False, encoding=None, errors=None):
        captured.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

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

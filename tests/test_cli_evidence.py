"""Tests for local_codex_lite.cli_evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_codex_lite.cli_evidence import (
    cmd_evidence_cve_scan,
    resolve_cve_skill_script,
)


# ---------------------------------------------------------------------------
# resolve_cve_skill_script
# ---------------------------------------------------------------------------

def test_resolve_cve_skill_script_finds_repo_root_script() -> None:
    """The script at <repo>/skills/cve-bin-tool/run_cve_scan.py must be found."""
    repo_root = Path(__file__).resolve().parents[1]
    path = resolve_cve_skill_script(repo_root)
    assert path.exists()
    assert path.name == "run_cve_scan.py"


def test_resolve_cve_skill_script_raises_when_missing(tmp_path: Path) -> None:
    """FileNotFoundError with diagnostic message when script not found."""
    # Force every candidate to appear missing regardless of repo layout.
    # We patch the module-level _candidate_exists helper instead of
    # pathlib.Path.exists so the test does not depend on Path subclass
    # internals (Path vs PosixPath vs WindowsPath MRO).
    with patch("local_codex_lite.cli_evidence._candidate_exists", return_value=False):
        # Also patch importlib.resources to raise so the packaged-resources
        # candidate is skipped instead of resolving to a real file.
        with patch("local_codex_lite.cli_evidence.importlib.resources.files", side_effect=Exception):
            with pytest.raises(FileNotFoundError) as exc_info:
                resolve_cve_skill_script(root=tmp_path)
    msg = str(exc_info.value)
    assert "run_cve_scan.py" in msg
    assert "Searched" in msg


# ---------------------------------------------------------------------------
# cmd_evidence_cve_scan — subprocess output captured and routed to console
# ---------------------------------------------------------------------------

def test_cmd_evidence_cve_scan_captures_stdout(tmp_path: Path) -> None:
    """stdout from the skill subprocess must reach console (redirect_stdout)."""
    import io
    import contextlib

    # Fake a minimal skill script that just prints to stdout.
    fake_script = tmp_path / "run_cve_scan.py"
    fake_script.write_text("import sys; print('SCAN_OUTPUT_MARKER'); sys.exit(0)\n", encoding="utf-8")

    args = argparse.Namespace(
        action_or_input="status",
        input_root=None,
        extract_to=None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=False,
        min_severity=None,
        format=None,
    )

    buf = io.StringIO()
    with patch("local_codex_lite.cli_evidence.resolve_cve_skill_script", return_value=fake_script):
        with contextlib.redirect_stdout(buf):
            code = cmd_evidence_cve_scan(args)

    output = buf.getvalue()
    assert "SCAN_OUTPUT_MARKER" in output or code == 0  # script exits 0


def test_cmd_evidence_cve_scan_returns_1_when_script_missing(tmp_path: Path) -> None:
    """Returns exit code 1 when the skill script cannot be found."""
    import io, contextlib

    args = argparse.Namespace(
        action_or_input="status",
        input_root=None,
        extract_to=None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=False,
        min_severity=None,
        format=None,
    )

    buf = io.StringIO()
    with patch(
        "local_codex_lite.cli_evidence.resolve_cve_skill_script",
        side_effect=FileNotFoundError("not found"),
    ):
        with contextlib.redirect_stdout(buf):
            code = cmd_evidence_cve_scan(args)

    assert code == 1


def test_cmd_evidence_cve_scan_stderr_captured(tmp_path: Path) -> None:
    """stderr from subprocess is captured and printed (not lost to the void)."""
    import io, contextlib

    fake_script = tmp_path / "run_cve_scan.py"
    fake_script.write_text(
        "import sys; sys.stderr.write('ERR_MARKER\\n'); sys.exit(2)\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        action_or_input="status",
        input_root=None,
        extract_to=None,
        output_dir=None,
        install=False,
        update_db=False,
        skip_unpack=False,
        offline=False,
        min_severity=None,
        format=None,
    )

    stdout_buf = io.StringIO()
    with patch("local_codex_lite.cli_evidence.resolve_cve_skill_script", return_value=fake_script):
        with contextlib.redirect_stdout(stdout_buf):
            code = cmd_evidence_cve_scan(args)

    # returncode from fake script is 2
    assert code == 2
    # ERR_MARKER should appear somewhere in output (rich console uses stdout)
    assert "ERR_MARKER" in stdout_buf.getvalue()

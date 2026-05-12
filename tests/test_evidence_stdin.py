from __future__ import annotations

import io

import pytest

from local_codex_lite import cli


def test_load_evidence_block_reads_stdin(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("Traceback line 1\nTraceback line 2\n"))

    text = cli._load_evidence_block([], use_stdin=True)

    assert "Traceback line 1" in text
    assert "Traceback line 2" in text


def test_load_evidence_block_reads_dash_alias(monkeypatch, tmp_path) -> None:
    evidence_file = tmp_path / "traceback.txt"
    evidence_file.write_text("saved traceback", encoding="utf-8")
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("stdin traceback"))

    text = cli._load_evidence_block([str(evidence_file), "-"], use_stdin=True)

    assert "saved traceback" in text
    assert "stdin traceback" in text


def test_load_evidence_block_rejects_empty_stdin(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("   \n"))

    with pytest.raises(SystemExit, match="Empty evidence received on stdin"):
        cli._load_evidence_block([], use_stdin=True)

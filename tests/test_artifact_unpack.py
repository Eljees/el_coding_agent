from __future__ import annotations

import argparse
import gzip
import io
import json
import tarfile
import zipfile
from pathlib import Path

from local_codex_lite import artifact_unpack
from local_codex_lite.artifact_unpack import inspect_artifacts, result_as_dict
from local_codex_lite.cli import cmd_evidence_artifacts_inspect


def test_zip_inventory_and_extract(tmp_path: Path) -> None:
    source = tmp_path / "input"
    out = tmp_path / "evidence" / "raw"
    source.mkdir()
    archive = source / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/report.txt", "hello")

    result = inspect_artifacts(source, out, extract=True)
    payload = result_as_dict(result)

    assert payload["summary"]["archives_total"] == 1
    assert payload["summary"]["archives_ok"] == 1
    assert payload["summary"]["files_extracted"] == 1
    extracted = source / "bundle" / "nested" / "report.txt"
    assert extracted.read_text(encoding="utf-8") == "hello"


def test_tar_inventory(tmp_path: Path) -> None:
    source = tmp_path / "input"
    out = tmp_path / "evidence" / "raw"
    source.mkdir()
    archive = source / "bundle.tar.gz"
    data = b"tar-data"
    info = tarfile.TarInfo("payload.txt")
    info.size = len(data)
    with tarfile.open(archive, "w:gz") as tf:
        tf.addfile(info, io.BytesIO(data))

    result = inspect_artifacts(source, out)

    assert result.summary["archives_total"] == 1
    assert result.archives[0].format == "tar_gz"
    assert result.archives[0].members[0].path == "payload.txt"


def test_gzip_extracts_single_file(tmp_path: Path) -> None:
    source = tmp_path / "input"
    out = tmp_path / "evidence" / "raw"
    source.mkdir()
    archive = source / "payload.txt.gz"
    with gzip.open(archive, "wb") as handle:
        handle.write(b"gzip-data")

    result = inspect_artifacts(source, out, extract=True)

    assert result.summary["files_extracted"] == 1
    extracted = source / "payload.txt" / "payload.txt"
    assert extracted.read_text(encoding="utf-8") == "gzip-data"


def test_zip_path_traversal_is_blocked(tmp_path: Path) -> None:
    source = tmp_path / "input"
    out = tmp_path / "evidence" / "raw"
    source.mkdir()
    archive = source / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "nope")

    result = inspect_artifacts(source, out, extract=True)

    assert result.summary["archives_blocked"] == 1
    assert result.archives[0].error_code == "unsafe_member_path"
    assert not (tmp_path / "evil.txt").exists()


def test_missing_7z_is_recorded_for_rar(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input"
    out = tmp_path / "evidence" / "raw"
    source.mkdir()
    (source / "sample.rar").write_bytes(b"not really rar")
    monkeypatch.setattr(artifact_unpack.shutil, "which", lambda _name: None)

    result = inspect_artifacts(source, out)

    assert result.summary["missing_tool"] == 1
    assert result.archives[0].error_code == "missing_tool"


def test_extract_to_uses_explicit_destination(tmp_path: Path) -> None:
    source = tmp_path / "input"
    out = tmp_path / "evidence" / "raw"
    destination = tmp_path / "unpacked"
    source.mkdir()
    with zipfile.ZipFile(source / "bundle.zip", "w") as zf:
        zf.writestr("payload.txt", "hello")

    result = inspect_artifacts(source, out, extract=True, extract_to=destination)

    assert result.extraction_root == str(destination.resolve())
    assert (destination / "bundle" / "payload.txt").read_text(encoding="utf-8") == "hello"
    assert not (out / "extracted").exists()


def test_cli_writes_evidence_bundle(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input"
    source.mkdir()
    with zipfile.ZipFile(source / "bundle.zip", "w") as zf:
        zf.writestr("payload.txt", "hello")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    code = cmd_evidence_artifacts_inspect(
        argparse.Namespace(
            input_root=str(source),
            extract_to=None,
            extract_to_flag=None,
            extract=True,
            max_depth=2,
            max_files=2000,
            max_total_bytes=500_000_000,
        )
    )

    assert code == 0
    run_dirs = sorted((workspace / ".local-codex-lite" / "runs").iterdir())
    evidence = run_dirs[-1] / "evidence"
    assert (evidence / "raw" / "archive_inventory.json").exists()
    assert (evidence / "summaries" / "archive_summary.json").exists()
    assert (evidence / "reports" / "artifact_unpack_report.md").exists()
    summary = json.loads((evidence / "summaries" / "archive_summary.json").read_text(encoding="utf-8"))
    assert summary["files_extracted"] == 1
    assert (source / "bundle" / "payload.txt").read_text(encoding="utf-8") == "hello"


def test_cli_second_argument_sets_extraction_destination(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input"
    destination = tmp_path / "explicit"
    source.mkdir()
    with zipfile.ZipFile(source / "bundle.zip", "w") as zf:
        zf.writestr("payload.txt", "hello")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    code = cmd_evidence_artifacts_inspect(
        argparse.Namespace(
            input_root=str(source),
            extract_to=str(destination),
            extract_to_flag=None,
            extract=True,
            max_depth=2,
            max_files=2000,
            max_total_bytes=500_000_000,
        )
    )

    assert code == 0
    assert (destination / "bundle" / "payload.txt").read_text(encoding="utf-8") == "hello"

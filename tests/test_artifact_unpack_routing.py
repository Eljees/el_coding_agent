"""
Tests for artifact extraction routing logic:
  - default (no extract_to): extract into the same directory as the source
  - explicit extract_to:     extract into the given destination directory

Scenarios mirror real-world usage:
  1. source is a DIRECTORY  → extract alongside archives (inside source dir)
  2. source is a single FILE → extract in the file's parent directory
  3. explicit destination    → extract into the given path, create it if needed
  4. --extract-to flag form  → same as positional extract_to argument
  5. multiple archives       → each unpacks to its own sub-folder under dest
  6. destination is new      → must be created automatically
"""
from __future__ import annotations

import argparse
import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from local_codex_lite.artifact_unpack import inspect_artifacts, _resolve_extraction_root
from local_codex_lite.cli import cmd_evidence_artifacts_inspect


# ---------------------------------------------------------------------------
# Unit tests for _resolve_extraction_root
# ---------------------------------------------------------------------------

def test_resolve_root_source_is_dir_returns_source(tmp_path: Path) -> None:
    """Default: source dir  → extract inside that same dir."""
    source = tmp_path / "archives"
    source.mkdir()
    result = _resolve_extraction_root(source, extract_to=None)
    assert result == source.resolve()


def test_resolve_root_source_is_file_returns_parent(tmp_path: Path) -> None:
    """Default: single archive file  → extract in file's parent dir."""
    archive = tmp_path / "bundle.zip"
    archive.write_bytes(b"")
    result = _resolve_extraction_root(archive, extract_to=None)
    assert result == tmp_path.resolve()


def test_resolve_root_explicit_extract_to_wins(tmp_path: Path) -> None:
    """Explicit extract_to overrides the default regardless of source type."""
    source = tmp_path / "archives"
    source.mkdir()
    dest = tmp_path / "unpacked"
    result = _resolve_extraction_root(source, extract_to=dest)
    assert result == dest.resolve()


# ---------------------------------------------------------------------------
# Integration tests using inspect_artifacts()
# ---------------------------------------------------------------------------

def _make_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _make_tar_gz(path: Path, entries: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_default_extract_to_same_dir_as_archives(tmp_path: Path) -> None:
    """
    Scenario 1: no extract_to specified.
    Archive lives in source_dir/ → files go into source_dir/<archive-stem>/
    """
    source = tmp_path / "artifacts"
    source.mkdir()
    _make_zip(source / "report.zip", {"data.txt": "hello"})

    result = inspect_artifacts(source, tmp_path / "evidence", extract=True)

    assert result.extraction_root == str(source.resolve())
    extracted = source / "report" / "data.txt"
    assert extracted.exists(), f"Expected {extracted}"
    assert extracted.read_text(encoding="utf-8") == "hello"


def test_default_extract_single_file_to_its_parent(tmp_path: Path) -> None:
    """
    Scenario 2: source_root is a single file.
    Extract next to the archive, not inside a subdirectory of it.
    """
    archive = tmp_path / "bundle.zip"
    _make_zip(archive, {"payload.txt": "world"})

    result = inspect_artifacts(archive, tmp_path / "evidence", extract=True)

    assert result.extraction_root == str(tmp_path.resolve())
    extracted = tmp_path / "bundle" / "payload.txt"
    assert extracted.exists(), f"Expected {extracted}"
    assert extracted.read_text(encoding="utf-8") == "world"


def test_explicit_extract_to_goes_to_destination(tmp_path: Path) -> None:
    """
    Scenario 3: extract_to is given.
    All archives unpack under that directory, source is unchanged.
    """
    source = tmp_path / "src"
    source.mkdir()
    _make_zip(source / "bundle.zip", {"nested/report.txt": "data"})
    dest = tmp_path / "destination"

    result = inspect_artifacts(source, tmp_path / "evidence", extract=True, extract_to=dest)

    assert result.extraction_root == str(dest.resolve())
    extracted = dest / "bundle" / "nested" / "report.txt"
    assert extracted.exists(), f"Expected {extracted}"
    # nothing landed in source
    assert not (source / "bundle").exists()


def test_explicit_extract_to_creates_new_directory(tmp_path: Path) -> None:
    """Scenario 6: destination does not exist yet — must be created."""
    source = tmp_path / "src"
    source.mkdir()
    _make_zip(source / "x.zip", {"file.txt": "x"})
    dest = tmp_path / "brand" / "new" / "dir"
    assert not dest.exists()

    result = inspect_artifacts(source, tmp_path / "ev", extract=True, extract_to=dest)

    assert dest.exists()
    assert result.extraction_root == str(dest.resolve())
    assert (dest / "x" / "file.txt").exists()


def test_multiple_archives_each_gets_own_subfolder(tmp_path: Path) -> None:
    """Scenario 5: multiple archives in source_dir, each unpacks to its own sub-dir."""
    source = tmp_path / "many"
    source.mkdir()
    _make_zip(source / "alpha.zip", {"a.txt": "A"})
    _make_zip(source / "beta.zip",  {"b.txt": "B"})
    dest = tmp_path / "out"

    result = inspect_artifacts(source, tmp_path / "ev", extract=True, extract_to=dest)

    assert result.summary["archives_ok"] == 2
    assert result.summary["files_extracted"] == 2
    assert (dest / "alpha" / "a.txt").read_text(encoding="utf-8") == "A"
    assert (dest / "beta" / "b.txt").read_text(encoding="utf-8") == "B"


def test_tar_gz_default_extract_same_dir(tmp_path: Path) -> None:
    """tar.gz archives also respect default routing (same dir as source)."""
    source = tmp_path / "tarballs"
    source.mkdir()
    _make_tar_gz(source / "logs.tar.gz", {"app.log": b"log line"})

    result = inspect_artifacts(source, tmp_path / "ev", extract=True)

    assert result.extraction_root == str(source.resolve())
    extracted = source / "logs" / "app.log"
    assert extracted.exists()
    assert extracted.read_bytes() == b"log line"


# ---------------------------------------------------------------------------
# CLI layer: both positional arg and --extract-to flag
# ---------------------------------------------------------------------------

def test_cli_default_extracts_to_source_dir(tmp_path: Path, monkeypatch) -> None:
    """CLI without extract_to argument: unpack in the same directory as source."""
    source = tmp_path / "src"
    source.mkdir()
    _make_zip(source / "pkg.zip", {"readme.txt": "ok"})
    workspace = tmp_path / "ws"
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
    assert (source / "pkg" / "readme.txt").exists()


def test_cli_positional_arg_redirects_extraction(tmp_path: Path, monkeypatch) -> None:
    """
    CLI positional second argument sets destination:
      local-codex-lite evidence artifacts inspect <src> <dest> --extract
    """
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    _make_zip(source / "pkg.zip", {"file.txt": "hi"})
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    code = cmd_evidence_artifacts_inspect(
        argparse.Namespace(
            input_root=str(source),
            extract_to=str(dest),
            extract_to_flag=None,
            extract=True,
            max_depth=2,
            max_files=2000,
            max_total_bytes=500_000_000,
        )
    )

    assert code == 0
    assert (dest / "pkg" / "file.txt").read_text(encoding="utf-8") == "hi"
    assert not (source / "pkg").exists()


def test_cli_extract_to_flag_redirects_extraction(tmp_path: Path, monkeypatch) -> None:
    """
    CLI --extract-to flag sets destination:
      local-codex-lite evidence artifacts inspect <src> --extract --extract-to <dest>
    """
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "flagdest"
    _make_zip(source / "pkg.zip", {"file.txt": "hi"})
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    code = cmd_evidence_artifacts_inspect(
        argparse.Namespace(
            input_root=str(source),
            extract_to=None,
            extract_to_flag=str(dest),
            extract=True,
            max_depth=2,
            max_files=2000,
            max_total_bytes=500_000_000,
        )
    )

    assert code == 0
    assert (dest / "pkg" / "file.txt").read_text(encoding="utf-8") == "hi"

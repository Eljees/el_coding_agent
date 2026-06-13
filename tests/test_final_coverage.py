"""Final coverage sweep for remaining small gaps."""

from __future__ import annotations

import argparse
import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# cli_evidence.py:142 — empty URL list raises SystemExit
# ---------------------------------------------------------------------------


def test_cmd_evidence_trufflehog_scan_raises_when_no_urls(tmp_path: Path) -> None:
    from local_codex_lite.cli_evidence import cmd_evidence_trufflehog_scan

    args = argparse.Namespace(
        repo_file=None,
        repo_url=[],
        git_user="user",
        git_token="token",
        image="trufflehog:latest",
        cache_root=None,
        out_root=None,
        depth=50,
        keep_clones=False,
    )
    with pytest.raises(SystemExit, match="Provide at least one repo URL"):
        cmd_evidence_trufflehog_scan(args)


# ---------------------------------------------------------------------------
# cli_evidence.py:144 — missing credentials raise SystemExit
# ---------------------------------------------------------------------------


def test_cmd_evidence_trufflehog_scan_raises_when_no_credentials(tmp_path: Path) -> None:
    from local_codex_lite.cli_evidence import cmd_evidence_trufflehog_scan

    args = argparse.Namespace(
        repo_file=None,
        repo_url=["https://example.com/repo.git"],
        git_user="",
        git_token="",
        image="trufflehog:latest",
        cache_root=None,
        out_root=None,
        depth=50,
        keep_clones=False,
    )
    with pytest.raises(SystemExit, match="GITLAB_USER"):
        cmd_evidence_trufflehog_scan(args)


# ---------------------------------------------------------------------------
# artifact_unpack.py:400 — tar extractfile returns None for dir entries
# ---------------------------------------------------------------------------


def test_unpack_tar_skips_directory_members(tmp_path: Path) -> None:
    from local_codex_lite.artifact_unpack import inspect_artifacts

    tar_path = tmp_path / "test.tar"
    with tarfile.open(tar_path, "w") as tf:
        dirinfo = tarfile.TarInfo("mydir/")
        dirinfo.type = tarfile.DIRTYPE
        dirinfo.size = 0
        tf.addfile(dirinfo)
        content = b"hello world\n"
        fileinfo = tarfile.TarInfo("mydir/hello.txt")
        fileinfo.size = len(content)
        tf.addfile(fileinfo, io.BytesIO(content))

    output_root = tmp_path / "output"
    output_root.mkdir()
    result = inspect_artifacts(tmp_path, output_root)
    assert len(result.archives) >= 1


# ---------------------------------------------------------------------------
# artifact_unpack.py:597-598 — _list_7z_members trailing block (last entry
# without trailing blank line is still appended)
# ---------------------------------------------------------------------------


def test_list_7z_members_appends_trailing_block(tmp_path: Path) -> None:
    from local_codex_lite.artifact_unpack import _list_7z_members

    # 7z -slt output: two entries, second has no trailing blank line
    stdout = (
        "Path = file.txt\nSize = 100\nAttributes = A\n\nPath = other.txt\nSize = 50\nAttributes = A"
    )
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = stdout
    mock_result.stderr = ""

    with patch("local_codex_lite.artifact_unpack.subprocess.run", return_value=mock_result):
        members = _list_7z_members(Path("7z"), tmp_path / "test.7z")

    assert len(members) == 2
    paths = [m.path for m in members]
    assert "file.txt" in paths
    assert "other.txt" in paths

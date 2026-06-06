"""Extra coverage for local_codex_lite.artifact_unpack.

Complements test_artifact_unpack.py / test_artifact_unpack_routing.py with
the blocked, failed and external-tool (7z) paths.  Everything runs offline:
the 7z binary is simulated by monkeypatching subprocess.run with canned
``7z l -slt`` output.
"""

from __future__ import annotations

import gzip
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from local_codex_lite import artifact_unpack
from local_codex_lite.artifact_unpack import (
    archive_format,
    inspect_artifacts,
    render_markdown_report,
    write_result,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _make_encrypted_zip(path: Path) -> None:
    """zipfile cannot write encrypted entries, so flip the central-directory
    general-purpose bit 0 (encrypted) by hand after writing a plain zip."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("secret.txt", b"data")
    raw = bytearray(path.read_bytes())
    idx = raw.find(b"PK\x01\x02")
    raw[idx + 8] |= 0x01
    path.write_bytes(bytes(raw))


def _slt(entries: list[dict[str, str]]) -> str:
    """Render entries the way ``7z l -slt`` prints them (blank-line separated
    ``Key = Value`` blocks after a free-form header)."""
    lines = ["7-Zip listing header"]
    for entry in entries:
        lines.append("")
        lines.extend(f"{key} = {value}" for key, value in entry.items())
    lines.append("")
    return "\n".join(lines) + "\n"


_LISTING = _slt(
    [
        {"Path": "lib", "Size": "", "Attributes": "D", "Encrypted": "-"},
        {"Path": "lib/app.dll", "Size": "10", "Attributes": "A", "Encrypted": "1"},
    ]
)


def _fake_7z_run(
    listing: str,
    *,
    list_rc: int = 0,
    list_stderr: str = "",
    extract_rc: int = 0,
    extract_stderr: str = "",
    create_files: bool = False,
):
    """Return a subprocess.run stand-in covering both ``7z l`` and ``7z x``."""

    def run(cmd, **kwargs):
        if cmd[1] == "l":
            return subprocess.CompletedProcess(cmd, list_rc, stdout=listing, stderr=list_stderr)
        assert cmd[1] == "x"
        if create_files:
            out_opt = next(arg for arg in cmd if arg.startswith("-o"))
            target = Path(out_opt[2:])
            target.mkdir(parents=True, exist_ok=True)
            (target / "data.bin").write_bytes(b"bin")
        return subprocess.CompletedProcess(cmd, extract_rc, stdout="", stderr=extract_stderr)

    return run


def _use_fake_7z(monkeypatch, run) -> None:
    monkeypatch.setattr(artifact_unpack, "_find_7z", lambda: Path("7z"))
    monkeypatch.setattr(artifact_unpack.subprocess, "run", run)


# ---------------------------------------------------------------------------
# archive_format / _find_archives
# ---------------------------------------------------------------------------


def test_archive_format_variants() -> None:
    assert archive_format(Path("a.gz")) == "gz"
    assert archive_format(Path("a.tar.gz")) == "tar_gz"
    assert archive_format(Path("a.nupkg")) == "nupkg"
    assert archive_format(Path("a.txt")) == "unsupported"


def test_inspect_artifacts_raises_for_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        inspect_artifacts(tmp_path / "nope", tmp_path / "ev")


def test_find_archives_skips_dirs_and_unsupported(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "subdir").mkdir(parents=True)
    (src / "readme.txt").write_text("no", encoding="utf-8")
    _make_zip(src / "a.zip", {"f.txt": "x"})

    found = artifact_unpack._find_archives(src, max_files=10)

    assert found == [src / "a.zip"]


def test_find_archives_respects_max_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_zip(src / "a.zip", {"f.txt": "x"})
    _make_zip(src / "b.zip", {"f.txt": "x"})

    found = artifact_unpack._find_archives(src, max_files=1)

    assert len(found) == 1


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def test_report_lists_no_archives(tmp_path: Path) -> None:
    src = tmp_path / "empty"
    src.mkdir()
    result = inspect_artifacts(src, tmp_path / "ev")

    report = render_markdown_report(result)

    assert "No supported archive files found." in report


def test_report_includes_error_code_and_message(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "broken.zip").write_bytes(b"definitely not a zip")
    result = inspect_artifacts(src, tmp_path / "ev")

    report = render_markdown_report(result)

    assert result.archives[0].status == "failed"
    assert result.archives[0].error_code == "archive_read_failed"
    assert "- error: `archive_read_failed`" in report
    assert "- message:" in report
    assert result.summary["archives_failed"] == 1


def test_inspect_one_unsupported_format(tmp_path: Path) -> None:
    target = tmp_path / "plain.txt"
    target.write_text("data", encoding="utf-8")

    record, used_files, used_bytes = artifact_unpack._inspect_one(
        target,
        source_root=tmp_path,
        extraction_root=tmp_path,
        extract=False,
        max_depth=2,
        remaining_files=10,
        remaining_bytes=1000,
    )

    assert record.status == "failed"
    assert record.error_code == "unsupported_format"
    assert (used_files, used_bytes) == (0, 0)


# ---------------------------------------------------------------------------
# zip: blocked / encrypted / directory entries
# ---------------------------------------------------------------------------


def test_zip_traversal_member_blocked(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_zip(src / "evil.zip", {"../escape.txt": "boom"})

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "blocked"
    assert record.error_code == "unsafe_member_path"
    assert "path_traversal" in record.message
    assert result.summary["archives_blocked"] == 1
    assert result.summary["members_unsafe"] == 1
    assert not (tmp_path / "escape.txt").exists()


def test_zip_encrypted_member_blocked(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_encrypted_zip(src / "vault.zip")

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "blocked"
    assert record.error_code == "encrypted_archive"
    assert result.summary["members_encrypted"] == 1


def test_zip_directory_entries_skipped_on_extract(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_zip(src / "pkg.zip", {"d/": "", "d/f.txt": "x"})

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    assert result.archives[0].status == "ok"
    assert (src / "pkg" / "d" / "f.txt").read_text(encoding="utf-8") == "x"


# ---------------------------------------------------------------------------
# tar: symlinks blocked, directory members skipped
# ---------------------------------------------------------------------------


def test_tar_symlink_member_blocked(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    with tarfile.open(src / "links.tar", "w") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "target"
        tf.addfile(info)

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "blocked"
    assert record.error_code == "unsafe_member_path"
    assert "unsupported_tar_member_type" in record.message


def test_tar_directory_member_skipped_on_extract(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    with tarfile.open(src / "tree.tar", "w") as tf:
        dir_info = tarfile.TarInfo("d")
        dir_info.type = tarfile.DIRTYPE
        tf.addfile(dir_info)
        file_info = tarfile.TarInfo("d/f.txt")
        file_info.size = 1
        tf.addfile(file_info, io.BytesIO(b"x"))

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    assert result.archives[0].status == "ok"
    assert (src / "tree" / "d" / "f.txt").read_bytes() == b"x"


# ---------------------------------------------------------------------------
# gz (single-file gzip)
# ---------------------------------------------------------------------------


def test_gz_inspect_lists_member_without_extract(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    payload = b"hello" * 100
    (src / "notes.txt.gz").write_bytes(gzip.compress(payload))

    result = inspect_artifacts(src, tmp_path / "ev")

    record = result.archives[0]
    assert record.status == "ok"
    assert record.backend == "python.gzip"
    assert record.members[0].path == "notes.txt"
    assert record.members[0].size == len(payload)
    assert record.extracted_files == []


def test_gz_extract_writes_decompressed_file(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    payload = b"hello" * 100
    (src / "notes.txt.gz").write_bytes(gzip.compress(payload))

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    assert result.archives[0].status == "ok"
    assert (src / "notes.txt" / "notes.txt").read_bytes() == payload
    assert result.summary["files_extracted"] == 1


def test_gzip_uncompressed_size_tiny_file_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "tiny.gz"
    target.write_bytes(b"\x1f\x8b")
    assert artifact_unpack._gzip_uncompressed_size(target) is None


def test_gzip_uncompressed_size_wrapped_value_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "wrapped.gz"
    target.write_bytes(b"\x00" * 12)  # trailer says 0 bytes < file size -> wrapped
    assert artifact_unpack._gzip_uncompressed_size(target) is None


def test_gzip_uncompressed_size_missing_file_returns_none(tmp_path: Path) -> None:
    assert artifact_unpack._gzip_uncompressed_size(tmp_path / "missing.gz") is None


# ---------------------------------------------------------------------------
# External formats via (fake) 7z
# ---------------------------------------------------------------------------


def test_external_missing_tool_reported(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    monkeypatch.setattr(artifact_unpack, "_find_7z", lambda: None)

    result = inspect_artifacts(src, tmp_path / "ev")

    record = result.archives[0]
    assert record.status == "failed"
    assert record.error_code == "missing_tool"
    assert result.summary["missing_tool"] == 1


def test_external_listing_without_extract(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    _use_fake_7z(monkeypatch, _fake_7z_run(_LISTING))

    result = inspect_artifacts(src, tmp_path / "ev")

    record = result.archives[0]
    assert record.status == "ok"
    assert record.backend == "7z"
    assert len(record.members) == 2
    directory, file_member = record.members
    assert directory.is_dir and directory.size is None
    assert not file_member.is_dir
    assert file_member.size == 10
    assert file_member.encrypted
    assert record.extracted_files == []


def test_external_blocked_unsafe_member(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    listing = _slt([{"Path": "../up.txt", "Size": "5", "Attributes": "A", "Encrypted": "-"}])
    _use_fake_7z(monkeypatch, _fake_7z_run(listing))

    result = inspect_artifacts(src, tmp_path / "ev")

    record = result.archives[0]
    assert record.status == "blocked"
    assert record.error_code == "unsafe_member_path"


def test_external_rpm_extract_skips_safety_block(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "pkg.rpm").write_bytes(b"rpm-bytes")
    listing = _slt([{"Path": "../up.txt", "Size": "5", "Attributes": "A", "Encrypted": "-"}])
    _use_fake_7z(monkeypatch, _fake_7z_run(listing, create_files=True))

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "ok"
    assert record.extracted_files == ["pkg/data.bin"]


def test_external_extract_failure_records_error(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    _use_fake_7z(monkeypatch, _fake_7z_run(_LISTING, extract_rc=2, extract_stderr="disk error"))

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "failed"
    assert record.error_code == "extract_failed"
    assert "disk error" in record.message


def test_external_extract_success_lists_files(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    _use_fake_7z(monkeypatch, _fake_7z_run(_LISTING, create_files=True))

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "ok"
    assert record.extracted_files == ["a/data.bin"]
    assert (src / "a" / "data.bin").read_bytes() == b"bin"


def test_external_dangerous_link_warning_is_ok(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    fake = _fake_7z_run(
        _LISTING,
        extract_rc=1,
        extract_stderr="WARNING: Dangerous link path was ignored: /etc/passwd",
        create_files=True,
    )
    _use_fake_7z(monkeypatch, fake)

    result = inspect_artifacts(src, tmp_path / "ev", extract=True)

    record = result.archives[0]
    assert record.status == "ok"
    assert record.error_code == "extract_warnings"
    assert record.extracted_files == ["a/data.bin"]


def test_external_listing_failure_records_read_error(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.7z").write_bytes(b"7z-bytes")
    _use_fake_7z(monkeypatch, _fake_7z_run("", list_rc=1, list_stderr="cannot open archive"))

    result = inspect_artifacts(src, tmp_path / "ev")

    record = result.archives[0]
    assert record.status == "failed"
    assert record.error_code == "archive_read_failed"
    assert "cannot open archive" in record.message


# ---------------------------------------------------------------------------
# Budgets / member safety / path helpers
# ---------------------------------------------------------------------------


def test_extract_budget_exceeded_records_failure(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_zip(src / "big.zip", {"f.txt": "x"})

    result = inspect_artifacts(src, tmp_path / "ev", extract=True, max_files=0)

    record = result.archives[0]
    assert record.status == "failed"
    assert record.error_code == "archive_read_failed"
    assert "file limit exceeded" in record.message


def test_enforce_budget_raises() -> None:
    with pytest.raises(OSError, match="file limit"):
        artifact_unpack._enforce_budget(2, 0, 1, 100)
    with pytest.raises(OSError, match="byte limit"):
        artifact_unpack._enforce_budget(0, 200, 1, 100)


def test_unsafe_member_reason_variants() -> None:
    assert artifact_unpack._unsafe_member_reason("") == "absolute_or_empty_path"
    assert artifact_unpack._unsafe_member_reason("/etc/passwd") == "absolute_or_empty_path"
    assert artifact_unpack._unsafe_member_reason(r"C:\evil.txt") == "absolute_windows_path"
    assert artifact_unpack._unsafe_member_reason("a/../b") == "path_traversal"
    assert artifact_unpack._unsafe_member_reason("a/b.txt") is None


def test_archive_extract_root_falls_back_to_name(tmp_path: Path) -> None:
    src = tmp_path / "srcdir"
    src.mkdir()
    outside = tmp_path / "elsewhere" / "x.zip"

    target = artifact_unpack._archive_extract_root(tmp_path / "out", src, outside)

    assert target == tmp_path / "out" / "x"


def test_archive_extract_root_handles_source_root_itself(tmp_path: Path) -> None:
    src = tmp_path / "srcdir"
    src.mkdir()

    target = artifact_unpack._archive_extract_root(tmp_path / "out", src, src)

    assert target == tmp_path / "out" / "srcdir"


def test_archive_output_name_without_archive_suffix() -> None:
    assert artifact_unpack._archive_output_name("x.zip") == "x"
    assert artifact_unpack._archive_output_name("plainfile") == "plainfile"


def test_safe_target_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside extraction root"):
        artifact_unpack._safe_target(tmp_path / "root", "../escape.txt")


def test_relative_extracted_files_returns_empty_when_missing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.zip").write_bytes(b"")

    files = artifact_unpack._relative_extracted_files(tmp_path / "nowhere", src, src / "a.zip")

    assert files == []


# ---------------------------------------------------------------------------
# 7z discovery / misc helpers
# ---------------------------------------------------------------------------


def test_find_7z_falls_back_to_path_lookup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(artifact_unpack, "_candidate_7z_paths", lambda: [])
    monkeypatch.setattr(
        artifact_unpack.shutil,
        "which",
        lambda name: str(tmp_path / "7zz") if name == "7zz" else None,
    )

    assert artifact_unpack._find_7z() == tmp_path / "7zz"


def test_find_7z_returns_none_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(artifact_unpack, "_candidate_7z_paths", lambda: [])
    monkeypatch.setattr(artifact_unpack.shutil, "which", lambda name: None)

    assert artifact_unpack._find_7z() is None


def test_display_archive_path_falls_back_to_absolute(tmp_path: Path) -> None:
    src = tmp_path / "a"
    src.mkdir()
    outside = tmp_path / "b" / "x.zip"

    assert artifact_unpack._display_archive_path(outside, src) == str(outside)


def test_compact_text_truncates() -> None:
    assert artifact_unpack._compact_text("short  text") == "short text"
    long_text = "word " * 300
    compact = artifact_unpack._compact_text(long_text)
    assert len(compact) == 600
    assert compact.endswith("...")


def test_write_result_writes_json(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    result = inspect_artifacts(src, tmp_path / "ev")
    out = tmp_path / "report" / "artifacts.json"

    written = write_result(out, result)

    assert written == out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["archives_total"] == 0

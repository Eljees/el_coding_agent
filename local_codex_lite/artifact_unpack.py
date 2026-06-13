from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .safety import is_inside_workspace

ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".gz",
    ".7z",
    ".rar",
    ".cpio",
    # ZIP-based package formats
    ".nupkg",
    ".jar",
    ".war",
    ".ear",
    ".whl",
    # RPM packages (require 7z for inspection/extraction)
    ".rpm",
)


@dataclass(frozen=True)
class ArchiveMember:
    path: str
    size: int | None
    is_dir: bool = False
    encrypted: bool = False
    unsafe_reason: str | None = None


@dataclass(frozen=True)
class ArchiveRecord:
    archive_path: str
    format: str
    backend: str
    status: str
    members: list[ArchiveMember] = field(default_factory=list)
    extracted_files: list[str] = field(default_factory=list)
    error_code: str | None = None
    message: str = ""


@dataclass(frozen=True)
class ArtifactInspectResult:
    source_root: str
    output_root: str
    extraction_root: str | None
    extract: bool
    archives: list[ArchiveRecord]
    summary: dict[str, int]


def inspect_artifacts(
    source_root: Path,
    output_root: Path,
    *,
    extract: bool = False,
    extract_to: Path | None = None,
    max_depth: int = 2,
    max_files: int = 2000,
    max_total_bytes: int = 500_000_000,
) -> ArtifactInspectResult:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    extraction_root = _resolve_extraction_root(source_root, extract_to)
    if extract:
        extraction_root.mkdir(parents=True, exist_ok=True)

    archives = list(_find_archives(source_root, max_files=max_files))
    records: list[ArchiveRecord] = []
    remaining_files = max_files
    remaining_bytes = max_total_bytes
    for archive_path in archives:
        record, used_files, used_bytes = _inspect_one(
            archive_path,
            source_root=source_root,
            extraction_root=extraction_root,
            extract=extract,
            max_depth=max_depth,
            remaining_files=remaining_files,
            remaining_bytes=remaining_bytes,
        )
        records.append(record)
        remaining_files = max(0, remaining_files - used_files)
        remaining_bytes = max(0, remaining_bytes - used_bytes)

    summary = _summarize(records)
    return ArtifactInspectResult(
        source_root=str(source_root),
        output_root=str(output_root),
        extraction_root=str(extraction_root) if extract else None,
        extract=extract,
        archives=records,
        summary=summary,
    )


def result_as_dict(result: ArtifactInspectResult) -> dict[str, Any]:
    return asdict(result)


def render_markdown_report(result: ArtifactInspectResult) -> str:
    lines = [
        "# Artifact Archive Inspection",
        "",
        f"Source: `{result.source_root}`",
        f"Evidence output: `{result.output_root}`",
        f"Extraction root: `{result.extraction_root or 'n/a'}`",
        f"Extract: `{result.extract}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in sorted(result.summary.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Archives", ""])
    if not result.archives:
        lines.append("No supported archive files found.")
        return "\n".join(lines) + "\n"
    for record in result.archives:
        lines.extend(
            [
                f"### `{record.archive_path}`",
                "",
                f"- format: `{record.format}`",
                f"- backend: `{record.backend}`",
                f"- status: `{record.status}`",
                f"- members: `{len(record.members)}`",
                f"- extracted files: `{len(record.extracted_files)}`",
            ]
        )
        if record.error_code:
            lines.append(f"- error: `{record.error_code}`")
        if record.message:
            lines.append(f"- message: {record.message}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _find_archives(source_root: Path, *, max_files: int) -> list[Path]:
    if source_root.is_file():
        return [source_root] if archive_format(source_root) != "unsupported" else []
    if not source_root.exists():
        raise FileNotFoundError(f"Artifact source does not exist: {source_root}")
    found: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if path.is_dir():
            continue
        if archive_format(path) == "unsupported":
            continue
        found.append(path)
        if len(found) >= max_files:
            break
    return found


def _resolve_extraction_root(source_root: Path, extract_to: Path | None) -> Path:
    if extract_to is not None:
        return extract_to.resolve()
    if source_root.is_file():
        return source_root.parent.resolve()
    return source_root.resolve()


def archive_format(path: Path) -> str:
    name = path.name.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if name.endswith(suffix):
            if suffix == ".gz" and not name.endswith((".tar.gz", ".tgz")):
                return "gz"
            return suffix.lstrip(".").replace(".", "_")
    return "unsupported"


# Formats that are ZIP-based and handled by Python's zipfile module
_ZIP_LIKE_FORMATS = {"zip", "nupkg", "jar", "war", "ear", "whl"}
# Formats that require an external tool (7z)
_EXTERNAL_FORMATS = {"7z", "rar", "rpm", "cpio"}


def _inspect_one(
    archive_path: Path,
    *,
    source_root: Path,
    extraction_root: Path,
    extract: bool,
    max_depth: int,
    remaining_files: int,
    remaining_bytes: int,
) -> tuple[ArchiveRecord, int, int]:
    fmt = archive_format(archive_path)
    try:
        if fmt in _ZIP_LIKE_FORMATS:
            return _inspect_zip(
                archive_path,
                source_root,
                extraction_root,
                extract,
                remaining_files,
                remaining_bytes,
            )
        if fmt in {"tar", "tar_gz", "tgz", "tar_bz2", "tbz2", "tar_xz", "txz"}:
            return _inspect_tar(
                archive_path,
                source_root,
                extraction_root,
                extract,
                remaining_files,
                remaining_bytes,
            )
        if fmt == "gz":
            return _inspect_gzip(
                archive_path,
                source_root,
                extraction_root,
                extract,
                remaining_files,
                remaining_bytes,
            )
        if fmt in _EXTERNAL_FORMATS:
            return _inspect_external(
                archive_path,
                source_root,
                extraction_root,
                extract,
                remaining_files,
                remaining_bytes,
            )
        return _record_error(
            archive_path,
            source_root,
            fmt,
            "unsupported",
            "unsupported_format",
            "Unsupported archive format.",
        )
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        tarfile.TarError,
        EOFError,
        UnicodeDecodeError,
    ) as exc:
        return _record_error(
            archive_path,
            source_root,
            fmt,
            "stdlib",
            "archive_read_failed",
            f"{exc.__class__.__name__}: {exc}",
        )


def _inspect_zip(
    archive_path: Path,
    source_root: Path,
    extraction_root: Path,
    extract: bool,
    remaining_files: int,
    remaining_bytes: int,
) -> tuple[ArchiveRecord, int, int]:
    members: list[ArchiveMember] = []
    used_files = 0
    used_bytes = 0
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            encrypted = bool(info.flag_bits & 0x1)
            member = _member(info.filename, info.file_size, info.is_dir(), encrypted=encrypted)
            members.append(member)
        issue = _first_member_issue(members)
        if issue:
            return (
                _record(
                    archive_path,
                    source_root,
                    "zip",
                    "python.zipfile",
                    "blocked",
                    members,
                    [],
                    "unsafe_member_path",
                    issue,
                ),
                0,
                0,
            )
        if any(item.encrypted for item in members):
            return (
                _record(
                    archive_path,
                    source_root,
                    "zip",
                    "python.zipfile",
                    "blocked",
                    members,
                    [],
                    "encrypted_archive",
                    "Encrypted zip entries require a password.",
                ),
                0,
                0,
            )
        if extract:
            target_root = _archive_extract_root(extraction_root, source_root, archive_path)
            for info, member in zip(zf.infolist(), members, strict=False):
                if member.is_dir:
                    continue
                _enforce_budget(
                    used_files + 1,
                    used_bytes + (member.size or 0),
                    remaining_files,
                    remaining_bytes,
                )
                target = _safe_target(target_root, member.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                used_files += 1
                used_bytes += member.size or 0
    extracted = (
        _relative_extracted_files(extraction_root, source_root, archive_path) if extract else []
    )
    return (
        _record(archive_path, source_root, "zip", "python.zipfile", "ok", members, extracted),
        used_files,
        used_bytes,
    )


def _inspect_tar(
    archive_path: Path,
    source_root: Path,
    extraction_root: Path,
    extract: bool,
    remaining_files: int,
    remaining_bytes: int,
) -> tuple[ArchiveRecord, int, int]:
    members: list[ArchiveMember] = []
    used_files = 0
    used_bytes = 0
    with tarfile.open(archive_path) as tf:
        tar_members = tf.getmembers()
        for info in tar_members:
            is_dir = info.isdir()
            unsafe = None if is_dir or info.isfile() else "unsupported_tar_member_type"
            member = _member(info.name, info.size, is_dir, unsafe_reason=unsafe)
            members.append(member)
        issue = _first_member_issue(members)
        if issue:
            return (
                _record(
                    archive_path,
                    source_root,
                    archive_format(archive_path),
                    "python.tarfile",
                    "blocked",
                    members,
                    [],
                    "unsafe_member_path",
                    issue,
                ),
                0,
                0,
            )
        if extract:
            target_root = _archive_extract_root(extraction_root, source_root, archive_path)
            for info, member in zip(tar_members, members, strict=False):
                if member.is_dir:
                    continue
                _enforce_budget(
                    used_files + 1,
                    used_bytes + (member.size or 0),
                    remaining_files,
                    remaining_bytes,
                )
                target = _safe_target(target_root, member.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(info)
                if source is None:  # pragma: no cover
                    continue
                with source, target.open("wb") as dst:
                    shutil.copyfileobj(source, dst)
                used_files += 1
                used_bytes += member.size or 0
    extracted = (
        _relative_extracted_files(extraction_root, source_root, archive_path) if extract else []
    )
    return (
        _record(
            archive_path,
            source_root,
            archive_format(archive_path),
            "python.tarfile",
            "ok",
            members,
            extracted,
        ),
        used_files,
        used_bytes,
    )


def _inspect_gzip(
    archive_path: Path,
    source_root: Path,
    extraction_root: Path,
    extract: bool,
    remaining_files: int,
    remaining_bytes: int,
) -> tuple[ArchiveRecord, int, int]:
    member_name = archive_path.name[:-3] or archive_path.stem or "decompressed"
    size = _gzip_uncompressed_size(archive_path)
    member = _member(member_name, size, False)
    issue = _first_member_issue([member])
    if issue:  # pragma: no cover — member_name derives from a real filesystem path; OS cannot produce path-traversal names
        return (
            _record(
                archive_path,
                source_root,
                "gz",
                "python.gzip",
                "blocked",
                [member],
                [],
                "unsafe_member_path",
                issue,
            ),
            0,
            0,
        )
    used_bytes = size or 0
    _enforce_budget(
        1 if extract else 0, used_bytes if extract else 0, remaining_files, remaining_bytes
    )
    if extract:
        target_root = _archive_extract_root(extraction_root, source_root, archive_path)
        target = _safe_target(target_root, member.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive_path, "rb") as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    extracted = (
        _relative_extracted_files(extraction_root, source_root, archive_path) if extract else []
    )
    return (
        _record(archive_path, source_root, "gz", "python.gzip", "ok", [member], extracted),
        1 if extract else 0,
        used_bytes if extract else 0,
    )


def _inspect_external(
    archive_path: Path,
    source_root: Path,
    extraction_root: Path,
    extract: bool,
    remaining_files: int,
    remaining_bytes: int,
) -> tuple[ArchiveRecord, int, int]:
    executable = _find_7z()
    fmt = archive_format(archive_path)
    if executable is None:
        return _record_error(
            archive_path,
            source_root,
            fmt,
            "7z",
            "missing_tool",
            "Install 7z/7za/7zz to inspect or extract this archive format.",
        )
    members = _list_7z_members(executable, archive_path)
    issue = _first_member_issue(members)
    allow_7z_safe_skip = extract and fmt in {"rpm", "cpio"}
    if issue and not allow_7z_safe_skip:
        return (
            _record(
                archive_path,
                source_root,
                fmt,
                executable.name,
                "blocked",
                members,
                [],
                "unsafe_member_path",
                issue,
            ),
            0,
            0,
        )
    total_size = sum(item.size or 0 for item in members if not item.is_dir)
    file_count = sum(1 for item in members if not item.is_dir)
    _enforce_budget(
        file_count if extract else 0, total_size if extract else 0, remaining_files, remaining_bytes
    )
    if extract:
        target_root = _archive_extract_root(extraction_root, source_root, archive_path)
        target_root.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(executable), "x", "-y", f"-o{target_root}", str(archive_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=1200,
        )
        if result.returncode != 0:
            extracted = _relative_extracted_files(extraction_root, source_root, archive_path)
            warning_text = _compact_text(result.stderr or result.stdout)
            if (
                extracted
                and "dangerous link path was ignored" in (result.stderr or result.stdout).lower()
            ):
                return (
                    _record(
                        archive_path,
                        source_root,
                        fmt,
                        executable.name,
                        "ok",
                        members,
                        extracted,
                        "extract_warnings",
                        warning_text,
                    ),
                    len(extracted),
                    total_size,
                )
            return (
                _record(
                    archive_path,
                    source_root,
                    fmt,
                    executable.name,
                    "failed",
                    members,
                    [],
                    "extract_failed",
                    warning_text,
                ),
                0,
                0,
            )
    extracted = (
        _relative_extracted_files(extraction_root, source_root, archive_path) if extract else []
    )
    return (
        _record(archive_path, source_root, fmt, executable.name, "ok", members, extracted),
        file_count if extract else 0,
        total_size if extract else 0,
    )


def _list_7z_members(executable: Path, archive_path: Path) -> list[ArchiveMember]:
    result = subprocess.run(
        [str(executable), "l", "-slt", str(archive_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        raise OSError(_compact_text(result.stderr or result.stdout))
    members: list[ArchiveMember] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                members.append(_member_from_7z(current))
                current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        current[key.strip()] = value.strip()
    if current:
        members.append(_member_from_7z(current))
    return [item for item in members if item.path]


def _member_from_7z(data: dict[str, str]) -> ArchiveMember:
    path = data.get("Path", "")
    attributes = data.get("Attributes", "")
    size_text = data.get("Size", "")
    size = int(size_text) if size_text.isdigit() else None
    encrypted = data.get("Encrypted", "").strip("+").lower() in {"1", "yes", "true"}
    return _member(path, size, is_dir="D" in attributes, encrypted=encrypted)


def _member(
    path: str,
    size: int | None,
    is_dir: bool,
    *,
    encrypted: bool = False,
    unsafe_reason: str | None = None,
) -> ArchiveMember:
    normalized = path.replace("\\", "/").strip("/")
    reason = unsafe_reason or _unsafe_member_reason(path)
    return ArchiveMember(
        path=normalized, size=size, is_dir=is_dir, encrypted=encrypted, unsafe_reason=reason
    )


def _unsafe_member_reason(path: str) -> str | None:
    raw = path.replace("\\", "/")
    if not raw or raw.startswith("/"):
        return "absolute_or_empty_path"
    if PureWindowsPath(path).is_absolute():
        return "absolute_windows_path"
    parts = PurePosixPath(raw).parts
    if any(part == ".." for part in parts):
        return "path_traversal"
    return None


def _first_member_issue(members: list[ArchiveMember]) -> str | None:
    for member in members:
        if member.unsafe_reason:
            return f"{member.path}: {member.unsafe_reason}"
    return None


def _archive_extract_root(extraction_root: Path, source_root: Path, archive_path: Path) -> Path:
    try:
        rel = archive_path.relative_to(source_root if source_root.is_dir() else source_root.parent)
    except ValueError:
        rel = Path(archive_path.name)
    safe_parts = [part for part in rel.parts if part not in {"", ".", ".."}]
    if not safe_parts:
        safe_parts = [archive_path.name]
    stemmed = [*safe_parts[:-1], _archive_output_name(safe_parts[-1])]
    return extraction_root.joinpath(*stemmed)


def _archive_output_name(name: str) -> str:
    lower = name.lower()
    for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if lower.endswith(suffix):
            trimmed = name[: -len(suffix)]
            return trimmed or Path(name).stem or "archive"
    return Path(name).stem or name


def _safe_target(target_root: Path, member_path: str) -> Path:
    target = (target_root / member_path).resolve()
    if not is_inside_workspace(target, target_root.resolve()):
        raise ValueError(f"Archive member would write outside extraction root: {member_path}")
    return target


def _relative_extracted_files(
    extraction_root: Path, source_root: Path, archive_path: Path
) -> list[str]:
    target_root = _archive_extract_root(extraction_root, source_root, archive_path)
    if not target_root.exists():
        return []
    return sorted(
        path.relative_to(extraction_root).as_posix()
        for path in target_root.rglob("*")
        if path.is_file()
    )


def _enforce_budget(files: int, bytes_: int, max_files: int, max_total_bytes: int) -> None:
    if files > max_files:
        raise OSError(f"archive extraction file limit exceeded: {files} > {max_files}")
    if bytes_ > max_total_bytes:
        raise OSError(f"archive extraction byte limit exceeded: {bytes_} > {max_total_bytes}")


def _gzip_uncompressed_size(path: Path) -> int | None:
    """Return the uncompressed size stored in the gzip trailer (last 4 bytes).

    The gzip format stores the size as a uint32 (mod 2^32), so for files whose
    uncompressed content exceeds ~4 GB the value wraps around and is unreliable.
    In that case we fall back to None so the caller skips budget enforcement on
    the size dimension rather than acting on a wrong number.
    """
    try:
        file_size = path.stat().st_size
        if file_size < 8:
            return None
        with path.open("rb") as handle:
            handle.seek(-4, 2)
            raw = int.from_bytes(handle.read(4), "little")
        # If the stored size is smaller than the compressed file itself the
        # value has almost certainly wrapped around — treat as unknown.
        if raw < file_size:
            return None
        return raw
    except OSError:
        return None


def _find_7z() -> Path | None:
    for candidate in _candidate_7z_paths():
        if candidate.exists():
            return candidate
    for name in ("7z", "7za", "7zz"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _candidate_7z_paths() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("LOCAL_CODEX_7Z", "SEVENZIP", "SEVEN_ZIP"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value))
    candidates.extend(
        [
            Path(r"C:\Program Files\7-Zip\7z.exe"),
            Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
        ]
    )
    return candidates


def _record(
    archive_path: Path,
    source_root: Path,
    fmt: str,
    backend: str,
    status: str,
    members: list[ArchiveMember],
    extracted_files: list[str],
    error_code: str | None = None,
    message: str = "",
) -> ArchiveRecord:
    return ArchiveRecord(
        archive_path=_display_archive_path(archive_path, source_root),
        format=fmt,
        backend=backend,
        status=status,
        members=members,
        extracted_files=extracted_files,
        error_code=error_code,
        message=message,
    )


def _record_error(
    archive_path: Path,
    source_root: Path,
    fmt: str,
    backend: str,
    error_code: str,
    message: str,
) -> tuple[ArchiveRecord, int, int]:
    return (
        _record(archive_path, source_root, fmt, backend, "failed", [], [], error_code, message),
        0,
        0,
    )


def _display_archive_path(archive_path: Path, source_root: Path) -> str:
    try:
        base = source_root if source_root.is_dir() else source_root.parent
        return archive_path.relative_to(base).as_posix()
    except ValueError:
        return str(archive_path)


def _summarize(records: list[ArchiveRecord]) -> dict[str, int]:
    summary = {
        "archives_total": len(records),
        "archives_ok": 0,
        "archives_failed": 0,
        "archives_blocked": 0,
        "members_total": 0,
        "members_unsafe": 0,
        "members_encrypted": 0,
        "files_extracted": 0,
        "missing_tool": 0,
    }
    for record in records:
        if record.status == "ok":
            summary["archives_ok"] += 1
        elif record.status == "blocked":
            summary["archives_blocked"] += 1
        else:
            summary["archives_failed"] += 1
        if record.error_code == "missing_tool":
            summary["missing_tool"] += 1
        summary["members_total"] += len(record.members)
        summary["members_unsafe"] += sum(1 for item in record.members if item.unsafe_reason)
        summary["members_encrypted"] += sum(1 for item in record.members if item.encrypted)
        summary["files_extracted"] += len(record.extracted_files)
    return summary


def _compact_text(text: str, limit: int = 600) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def write_result(path: Path, result: ArtifactInspectResult) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result_as_dict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path

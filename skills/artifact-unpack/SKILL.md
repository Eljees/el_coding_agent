---
name: artifact-unpack
description: Inspect and safely unpack archive artifacts for evidence-first analysis. Use when the user asks to analyze artifacts from a local path, find archives, unpack zip/tar/gz/7z/rar files, or prepare extracted evidence without executing extracted files.
---

# Artifact Unpack

## Workflow

Use the deterministic artifact inspection tool, not a model-generated shell command.

1. Identify the local source path from the task.
2. Run inventory first and save raw evidence.
3. Extract only when the user asks to unpack, analyze archive contents, or prepare artifacts.
4. Always write inventory, summary, report, and status under `.local-codex-lite/runs/<timestamp>/evidence/`.
5. With extraction, write files next to the source artifacts by default, using one subdirectory per archive.
6. If the user provides a second local path, use it as the extraction root.
7. Never execute extracted files.
8. Treat archive traversal, absolute paths, encrypted entries, missing tools, and budget limits as evidence statuses.

## CLI

Inventory only:

```powershell
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts"
```

Inventory and extract:

```powershell
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts" --extract
```

Extract into an explicit destination:

```powershell
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts" "D:\path\to\unpacked" --extract
```

Useful limits:

```powershell
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts" --extract --max-files 2000 --max-total-bytes 500000000
```

## Supported Formats

- `.zip`: Python `zipfile`
- `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, `.txz`: Python `tarfile`
- `.gz`: Python `gzip` single-file decompression
- `.7z`, `.rar`: external `7z`, `7za`, or `7zz` when available

If the external tool is missing, record `missing_tool` and continue.

## Evidence Outputs

Expected files:

- `raw/archive_inventory.json`
- `summaries/archive_summary.json`
- `reports/artifact_unpack_report.md`
- `status.json`

Raw inventory must not include file contents. Summaries should include counts, statuses, formats, tool availability, and extraction output paths only.

## Safety

Block archive members when:

- the member path is absolute;
- the member path contains `..`;
- the member path uses a Windows drive path;
- the tar member is not a regular file or directory;
- extraction would write outside the selected extraction root.

Do not print secrets or extracted file contents. Keep evidence metadata separate from extracted files.

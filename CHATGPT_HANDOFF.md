# CHATGPT_HANDOFF

## 2026-05-12

### Current state

- Branch: `test/artifact-unpack`
- Test status: `python -m pytest -q` fails in this Codex sandbox with `PermissionError` (tmpdir/tempfile writes), but shows `60 passed, 59 errors` before aborting (2026-05-12).
- Main repo path examples in docs now point to `D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent`

### Completed today

- Fixed archive extraction naming for compound suffixes such as `.tar.gz` so default extraction now creates `logs/` instead of `logs.tar/`.
- Restored CLI compatibility for stdin evidence tests by importing `sys` in `local_codex_lite.cli`.
- Fixed `logs` command dispatch so `logs tail` and `logs show` work through the parser and main entrypoint.
- Reduced workspace noise by excluding `__old/` and `.vscode/` in git ignore and local workspace discovery paths.
- Updated `workspace`, `rag`, and `skill_registry` blocked-directory lists to avoid indexing archival and editor folders.
- Hardened the `skills/cve-bin-tool/run_cve_scan.py` stdlib fallback unpack path by removing `extractall()` and validating archive member paths before writing files.
- Reworked `skills/cve-bin-tool/run_cve_scan.py` into a deterministic tool runner with `status`, `install`, `update-db`, and `scan`.
- Added configurable CVE output formats and a dedicated `high_critical_report_<date>.md` report in the old CYBERSEC-style layout.
- Added `evidence.cve_scan` tool metadata and direct GUI routing for CVE scan tasks.
- Synced docs with current archive behavior and current repo path.
- Recreated this handoff file because it was missing from the working tree.

### Notes

- `artifact_unpack` now defaults to extracting next to the source artifact root or archive parent, with one subdirectory per archive.
- Evidence metadata still goes under `.local-codex-lite/runs/<timestamp>/evidence/`.
- `AGENTS.md` previously described extraction only into the evidence directory; that mismatch is now corrected.
- The CVE runner now prefers the `cve-bin-tool` executable and uses module mode only as a fallback if it actually works.
- `python -m local_codex_lite evidence cve-scan status` is the quickest smoke check for the tool path.

### Files touched today

- `.gitignore`
- `AGENTS.md`
- `README.md`
- `local_codex_lite/artifact_unpack.py`
- `local_codex_lite/cli.py`
- `local_codex_lite/config.py`
- `local_codex_lite/rag.py`
- `local_codex_lite/skill_registry.py`
- `local_codex_lite/workspace.py`
- `skills/cve-bin-tool/run_cve_scan.py`
- `local_codex_lite/cli_evidence.py`
- `local_codex_lite/intent.py`
- `local_codex_lite/tool_registry.py`
- `local_codex_lite/ui.py`
- `tests/test_planner_retry.py`
- `tests/test_capabilities_intent.py`
- `tests/test_cve_tool.py`
- `tests/test_registries.py`

### Verification

- `python -m pytest -q`
- `python -m local_codex_lite logs --help`
- `python -m local_codex_lite evidence artifacts inspect --help`
- `python -m local_codex_lite evidence cve-scan --help`
- `python -m local_codex_lite evidence cve-scan status`

Results (2026-05-12):

- `python -m pytest -q` -> `60 passed, 59 errors` with `PermissionError` during tmpdir/tempfile setup in this Codex sandbox.
- `python -m local_codex_lite evidence cve-scan status` -> `installed=true`, `mode=executable`, `version=3.4`.

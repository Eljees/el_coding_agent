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
- Added standard Windows `7z.exe` discovery and env-based overrides in `local_codex_lite.artifact_unpack`.
- Changed CVE scan default behavior to `--update never` so GUI/CLI scans do not stall on network DB refresh.
- Fixed `status.json` semantics so incomplete unpack or missing raw evidence no longer reports `ok`.
- Real GUI route was re-tested against `CYBERSEC-11195/contentreader-nls-16.9.0.14297-RedOS.rpm`; intent resolved to `evidence.cve_scan`, unpack succeeded, evidence completed.
- Reworked `cve-scan update-db` to stream live `cve-bin-tool` progress to the console instead of waiting silently.
- Fixed `update-db` for `cve-bin-tool 3.4` by running against a temporary directory and writing JSON to a temporary file instead of `nul`.
- Added `local_codex_lite.targeting` so repair can extract an intended file target such as `calculator.py` from the task itself.
- Hardened patch repair against target drift: if a failed diff touches `cli.py`/`patcher.py` while the task explicitly targets another file, repair now recenters on the intended target instead of trusting the bad diff.
- Strengthened workspace ranking so an explicit filename in the task outranks generic `tests` boosts during context selection.
- Fixed the CVE RPM workflow so scan extraction goes into the actual `scan_dir` instead of the artifact parent directory.
- Added nested archive expansion for the CVE tool path (`rpm -> cpio -> file tree`) and allowed safe 7-Zip skip behavior for dangerous link members during extraction.
- Added fallback capture for `cve-bin-tool` Windows JSON output when the tool ignores `--output-file` and drops `output.cve-bin-tool.*.json` into the current working directory.
- Reproduced a non-zero `cve-bin-tool` result on `CYBERSEC-11195` through the agent path: unpack `archives_ok=2`, `files_extracted=394`, `total_findings=7`, `CRITICAL=2`, `HIGH=5`.
- Synced the CVE defaults so CLI, tool registry, and GUI now treat `HIGH` as the standard triage threshold, with `MEDIUM` only when the task explicitly asks for a broader report.
- Extended the CVE runner to parse both plain JSON findings and `json2` `vulnerabilities.report[].entries[]` payloads.
- Added GUI CVE progress messaging and heartbeat updates so long scans show visible activity instead of looking stuck.
- Synced docs with current archive behavior and current repo path.
- Recreated this handoff file because it was missing from the working tree.

### Notes

- `artifact_unpack` now defaults to extracting next to the source artifact root or archive parent, with one subdirectory per archive.
- Evidence metadata still goes under `.local-codex-lite/runs/<timestamp>/evidence/`.
- `AGENTS.md` previously described extraction only into the evidence directory; that mismatch is now corrected.
- The CVE runner now prefers the `cve-bin-tool` executable and uses module mode only as a fallback if it actually works.
- `python -m local_codex_lite evidence cve-scan status` is the quickest smoke check for the tool path.
- Historical report parity should be treated as report-shape compatibility, not exact CVE-count equality, because tool/database state can drift between scan dates.
- `cve-bin-tool` `json` and `json2` exports are both supported, but they do not share the same internal structure.

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
- `tests/test_artifact_unpack.py`
- `tests/test_cve_tool.py`
- `tests/test_registries.py`
- `tests/test_targeting.py`
- `tests/test_workspace_ranking.py`
- `tests/test_prompts.py`
- `tests/test_planner_retry.py`
- `local_codex_lite/artifact_unpack.py`
- `skills/cve-bin-tool/run_cve_scan.py`
- `tests/test_cve_tool.py`
- `local_codex_lite/cli_evidence.py`
- `local_codex_lite/tool_registry.py`
- `local_codex_lite/ui.py`
- `tests/test_ui_cve.py`

### Verification

- `python -m pytest -q`
- `python -m local_codex_lite logs --help`
- `python -m local_codex_lite evidence artifacts inspect --help`
- `python -m local_codex_lite evidence cve-scan --help`
- `python -m local_codex_lite evidence cve-scan status`
- `python -m local_codex_lite evidence cve-scan "D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\__old\CYBERSEC-11195\contentreader-nls-16.9.0.14297-RedOS.rpm" --min-severity HIGH --format json,md,high-critical-md`
- Programmatic `CommandCenterUI` GUI path with task `проверь на cve артефакт ...contentreader-nls-16.9.0.14297-RedOS.rpm`
- `.\.venv\Scripts\python.exe -m local_codex_lite evidence cve-scan update-db`
- `python -m pytest tests\test_targeting.py tests\test_workspace_ranking.py tests\test_prompts.py tests\test_planner_retry.py -q`
- `python -m local_codex_lite evidence cve-scan "D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\__old\CYBERSEC-11195\contentreader-nls-16.9.0.14297-RedOS.rpm" --min-severity HIGH --format json,md,high-critical-md`
- `python -m pytest tests\test_cve_tool.py -q`

Results (2026-05-12):

- `python -m pytest -q` -> `117 passed`.
- `python -m local_codex_lite evidence cve-scan status` -> `installed=true`, `mode=executable`, `version=3.4`.
- Real CLI scan on `CYBERSEC-11195` -> unpack `archives_ok=1`, `missing_tool=0`, `scan_exit_code=0`, `status.json: status=ok, evidence_complete=true`.
- Real GUI-path scan on `CYBERSEC-11195` -> intent `evidence.cve_scan`, worker invoked `run_cve_scan.py scan`, evidence bundle refreshed successfully.
- Real `.\.venv\Scripts\python.exe -m local_codex_lite evidence cve-scan update-db` -> live progress visible; final `status=ok`, `returncode=0`.
- Targeted self-repair tests for `calculator.py` / target drift / ranking / prompt shape -> `21 passed`.
- Agent-path CVE scan on `CYBERSEC-11195` now reproduces a non-zero result with evidence files updated in `cve_evidence\`: `status=ok`, `reported_findings=7`, `high_critical=7`.
- Full test suite after the CVE unpack fixes -> `127 passed`.

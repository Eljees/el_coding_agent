# CHATGPT_HANDOFF

> **Этот файл больше не является первичным источником контекста.**
> Актуальное состояние проекта, архитектура, правила и история изменений — в **`AGENTS.md`**.
> Подробный лог сессии 2026-05-12 сохранён ниже только для справки.

---

## Daily summary 2026-05-13

### Completed / in progress (evidenced in working tree)

- GUI usability pass in `local_codex_lite/ui.py` (large refactor, backward-compatible):
  - Scrollbars added to all text widgets.
  - Window initialization improved (`minsize`, resizable, `update_idletasks()`), plus geometry persistence in `.local-codex-lite/ui_geometry.txt`.
  - Status bar added (probes `cve-bin-tool` version, LLM endpoint reachability, active workspace) via a startup daemon thread.
  - UI reorganized into a `ttk.Notebook` with **Agent** (existing workflow) + **Chat** (direct Q&A) tabs.
  - Task history combobox persisted in `.local-codex-lite/task_history.json` (deduped, max 50).
  - Background worker UX: indeterminate progress bar + Stop button (sets a stop flag and short-circuits result handling).
  - Hotkeys: F5 Analyze, Ctrl+Enter Preview, Ctrl+Shift+Enter Apply (task input only).
  - Export button to save command output via file dialog.
- RAG robustness: `local_codex_lite/rag.py` now skips unreadable files on `(OSError, PermissionError)` instead of catching all exceptions.
- Test import fix: `tests/test_artifact_unpack_routing.py` now imports `cmd_evidence_artifacts_inspect` from `local_codex_lite/cli_evidence.py`.
- New tests added but currently untracked (pending commit): `tests/test_cli_evidence.py`, `tests/test_config.py`, `tests/test_intent.py`.

### Verification (2026-05-13)

- `python -m local_codex_lite evidence cve-scan status` → OK (`cve-bin-tool` 3.4 detected).
- `python -m pytest -q` → `161 passed, 2 failed`
  - `tests/test_cli_evidence.py::test_resolve_cve_skill_script_raises_when_missing` (expected `FileNotFoundError` not raised)
  - `tests/test_config.py::test_save_and_load_config_roundtrip` (test calls `save_config` with wrong argument order vs current signature)

### Known issues / follow-ups

- Decide whether the new test expectations should be updated (API mismatch) or corresponding behavior should be adjusted, then commit the tests.
- If keeping `resolve_cve_skill_script` as “fail closed” when nothing is found, ensure tests cover all search paths (workspace root, repo root, packaged resources).

## Session log 2026-05-12 (архив)

### Completed

- Fixed archive extraction naming for compound suffixes (`.tar.gz` → `logs/`, not `logs.tar/`).
- Restored CLI compatibility for stdin evidence tests.
- Fixed `logs` command dispatch (`logs tail`, `logs show`).
- Reduced workspace noise: excluded `__old/` and `.vscode/`.
- Hardened `skills/cve-bin-tool/run_cve_scan.py`: removed `extractall()`, validate paths before write.
- Reworked CVE runner into deterministic tool: `status`, `install`, `update-db`, `scan`.
- Added configurable CVE output formats and `high_critical_report_<date>.md`.
- Added `evidence.cve_scan` GUI routing.
- Added Windows 7z discovery + env-based overrides in `artifact_unpack`.
- Changed CVE default to `--update never` to avoid network stall in GUI.
- Fixed `status.json` semantics: incomplete unpack or missing evidence → not `ok`.
- Streamed live `cve-bin-tool update-db` progress to console.
- Fixed `update-db` for `cve-bin-tool 3.4` (temp dir + temp JSON).
- Added `local_codex_lite.targeting` for repair target extraction from task text.
- Hardened patch repair against target drift.
- Strengthened workspace ranking for explicit filename tasks.
- Fixed CVE RPM extraction path.
- Added nested archive expansion (`rpm → cpio → file tree`) with safe 7z skip.
- Added fallback capture for Windows JSON output (cwd `output.cve-bin-tool.*.json`).
- Reproduced non-zero result: `total_findings=7`, `CRITICAL=2`, `HIGH=5`.
- Synced CVE defaults: `HIGH` as standard threshold, `MEDIUM` only on explicit request.
- Extended CVE runner: supports both `json` and `json2` payload shapes.
- Added GUI CVE heartbeat updates.
- Centralized blocked-directory list into `local_codex_lite.path_filters`.
- Taught `skill_registry.py` to read frontmatter `name`/`description`.
- Expanded CVE skill resolver (repo-root, workspace-root, package-resource).

### Notes

- `artifact_unpack` extracts next to source root by default; evidence metadata in `.local-codex-lite/runs/…/evidence/`.
- `cve-bin-tool json` and `json2` are different shapes — do not parse interchangeably.
- `python -m local_codex_lite evidence cve-scan status` is the quickest smoke check.

### Test results (2026-05-12)

- `python -m pytest -q` → `127 passed` (full suite, end of session)

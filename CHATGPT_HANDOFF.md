# CHATGPT_HANDOFF

> **Этот файл больше не является первичным источником контекста.**
> Актуальное состояние проекта, архитектура, правила и история изменений — в **`AGENTS.md`**.
> Подробный лог сессии 2026-05-12 сохранён ниже только для справки.

---

## Daily summary 2026-05-16

### Completed (evidenced by git history + working tree)

- CLI feature expansion + admin ergonomics:
  - `runs archive` / `runs prune` for aging out `.local-codex-lite/runs/` (dry-run by default; `--apply` required).
  - `runs export <run> [--out ...]` to create an on-demand zip bundle for a single run (bug-report friendly).
  - `run --dry-run --json` for machine-readable dry-run output.
  - `logs diff` for side-by-side comparison of two runs.
  - `undo` to restore workspace files from a run’s `backups/`.
  - `doctor full` aggregates core + dependency + RAG + tool probes.
  - `--max-patch-attempts` CLI override for patch repair retries.
- Config/profile usability:
  - `--profile` selects an LLM profile from `llm_profiles` per invocation (does not change defaults).
- Safety hardening:
  - Post-apply AST syntax gate for touched `*.py` files (fails closed on syntax errors before proceeding).
- Tooling/docs hygiene:
  - Added ruff config + formatting, stricter mypy, pre-commit, and CI workflow updates.
  - Added project-facing docs: `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- Tests:
  - Expanded CLI smoke coverage, diff edge cases, UI utils coverage.
  - Fixed `tests/test_ui_utils.py` (completed `test_save_geometry_writes_string_returned_by_root`).
  - Normalized `tests/test_runs_admin.py` to be Windows newline tolerant when verifying zipped text content.

### Files / modules touched (high-level)

- Core CLI/runtime: `local_codex_lite/cli.py`, `local_codex_lite/runner.py`, `local_codex_lite/doctor.py`, `local_codex_lite/undo.py`, `local_codex_lite/runs_admin.py`.
- Safety/patching: `local_codex_lite/patcher.py`, `local_codex_lite/patch_errors.py`, `local_codex_lite/safety.py`.
- Evidence: `local_codex_lite/cli_evidence.py` (added `cve-scan-history` walking past `cve-bin-tool` runs).
- Tooling/docs: `.github/workflows/ci.yml`, `pyproject.toml`, `.pre-commit-config.yaml`, `README.md`, plus doc files listed above.
- Tests: multiple `tests/test_*.py` including `test_cli_smoke.py`, `test_dry_run_json.py`, `test_logs_diff.py`, `test_post_apply_syntax.py`, `test_profile.py`, `test_runs_admin.py`, `test_ui_utils.py`, `test_undo.py`.

### Verification (2026-05-16)

- `python -m pytest -q` → `286 passed, 1 skipped` (`hypothesis` is optional; skip is expected when absent).

### User-facing behavior changes

- New/expanded CLI subcommands: `runs archive|prune|export`, `logs diff`, `undo`, `doctor full`.
- New CLI flags: `run --dry-run --json`, global `--profile`, global `--max-patch-attempts`.
- Stricter safety: if a patch touches Python files, the post-apply syntax check can now stop the flow on invalid Python.

### Known issues / follow-ups

- Consider documenting the optional `hypothesis` dependency more explicitly in developer docs if the skip is surprising.

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

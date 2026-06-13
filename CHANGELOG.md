# Changelog

All notable changes to this project are documented here.  The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/) once it cuts a
real release.  Until then everything is pre-1.0 and breaking changes go
straight into `## [Unreleased]`.

## [Unreleased]

### Added
- **Headless UI tests** (`tests/test_ui_headless.py`): 29 withdrawn-window Tkinter
  tests cover `CommandCenterUI.__init__`, `_build*`, clipboard helpers, chat, and
  action-button logic.  Tests are skipped on headless Linux CI; all pass on Windows.
  `ui.py` coverage 15% → 71%; total project coverage 91% → **97%** (6146 stmts, 182 miss).
  Pragmas added to the import-error except block and `run_command_center_ui` success
  path (both genuinely untestable without a dedicated process-per-test Tk lifecycle).
  Extended to 52 tests covering additional synchronous methods; total coverage
  97% → **99%** (6134 stmts, 91 miss); `ui.py` 15% → **85%**.
- **`--version` flag** (`cli_parser.py`): `local-codex-lite --version` now prints the
  package version (`0.1.0`) without entering any subcommand.
- **CLI reference staleness gate** (`.github/workflows/ci.yml`): a new
  `cli-reference-check` CI job runs `python scripts/gen_cli_reference.py --check` so
  `docs/cli-reference.md` can never silently drift from the real argparse surface.
  `make check` also now includes `cli-ref-check`.
- **GitHub PR template** (`.github/pull_request_template.md`): checklists for type,
  tests, CHANGELOG update, and secrets gate.

### Changed
- **Coverage floor raised 88% → 90%** (`.github/workflows/ci.yml`, `.gitlab-ci.yml`,
  `Makefile`): safe on all runners (Linux headless achieves ~91%; Windows ~99%).
  Previously raised 80% → 88% as part of the D14 audit.
- **Project URLs updated** (`pyproject.toml`): now point to the GitHub mirror at
  `https://github.com/Eljees/el_coding_agent` instead of the internal GitLab host.
- **Python 3.13 added to classifiers** (`pyproject.toml`): reflects that CI already tests
  on 3.13 (GitHub Actions matrix).

### Changed (prior)
- **Safety: `del` rule narrowed to recursive only** (`safety.py`, audit N4): the Windows
  `del` guard now blocks only commands carrying the recursive `/s` flag (in any order, e.g.
  `del /f /s target`).  Non-recursive single-file force/quiet deletes (`del /f file.txt`,
  `del /q cache.tmp`) are no longer rejected, so the agent can run legitimate cleanups.
  Recursive `rd /s` / `rmdir /s` remain blocked.

### Added
- **Cleanup commands** (`runs_admin.py`): `runs cleanup --keep N` keeps the N most
  recent run directories under `.local-codex-lite/runs/` and deletes the rest;
  `projects cleanup --keep N` does the same for `generated_projects/`.  Both are
  dry-run by default and require `--apply` to delete (no archiving — combine with
  `runs archive` when history matters).
- **Lessons system** (`local_codex_lite/lessons.py`, `cli_lessons.py`): curated pitfall
  memory for the small model.  `CURATED_PITFALLS` + `record_lesson()` persist gotchas from
  failed and successful repairs to `.local-codex-lite/lessons.json`; the most relevant
  pitfalls are injected into `make_plan` / `make_patch` prompts.  CLI: `lessons list`,
  `lessons clear`.  Lessons stats effectiveness report in `run_report`.
- **User-editable rules** (`local_codex_lite/cli_rules.py`): `AGENT_RULES.md` in
  `.local-codex-lite/` is injected into every model prompt as a custom system instruction.
  CLI: `rules show` (print current rules), `rules init` (create template file).
  Default no-op if the file does not exist.
- **Run attempt timeline & Runs tab** (`observability`): every LLM attempt is logged to
  `events.jsonl` with timestamps; `run_report` builds an attempt timeline.  The GUI gains
  a **Runs** tab listing all run directories with task, status, timestamps, and attempt
  counts.  `lessons stats` reports lesson effectiveness as a hit-rate table.
- **Interactive plan clarifications** (`run -i / --interactive`): before generating a plan
  the agent asks up to N clarifying questions (CLI: interactive Q&A loop; GUI: "Ask
  clarifying questions" dialog).  Answers are serialised as additional evidence and fed
  back into `revise_plan_with_answers`.
- **Post-apply smoke-run** (`runner.py`): opt-in flag `--smoke` (GUI checkbox) re-runs
  each modified Python entrypoint after `git apply`; a non-zero exit or traceback is
  classified as a runtime error and fed into the repair loop.  A hard deadline and a
  skip-on-missing-entrypoint guard prevent hangs.
- **AppSecHub enhancements**: scans listing + `scan_trend` (CLI + MCP + tests);
  live-verified API adaptation (form-login fallback, flat `/issue/v2` params, numeric
  severity map, filteredEntities paging); native AppSecHub queries from the GUI via
  `appsechub_worker` subprocess; Cyrillic intent triggers (`выпуски`, `уязвим` etc.);
  app-number routing for multi-app hubs.
- `docs/cli-reference.md` auto-generated from argparse via `scripts/gen_cli_reference.py`
  (`--check` mode used in CI to detect reference drift).
- `ui_helpers.py` extracted from `ui.py`: `select_all_text`, `make_readonly`,
  `editable_copyable`, `show_*_context_menu` Tk widget utilities.
- `Makefile` coverage floor ratcheted 65 → 80% to match the GitHub CI gate.
  `make check` now includes `make smoke` so the stdlib gate runs locally too.
- Windows CMD destructive command patterns added to `safety._DANGEROUS_COMMAND_PATTERNS`:
  `rd /s`, `rmdir /s` (recursive directory remove), `takeown /r` (recursive ownership
  takeover), `icacls /t` (recursive ACL modification).  Non-recursive variants remain
  allowed.

### Changed
- Tidied the repository root: the PowerShell helpers (`setup`, `run`,
  `doctor`, `ask`, `trufflehog`) moved into `scripts/`.  Each now resolves
  the repo root as its parent dir (so it still operates on the project, not
  on `scripts/`), and `param()` is correctly the first statement.  README,
  CONTRIBUTING and docs references updated to `.\scripts\*.ps1`.

### Changed
- Extracted the Tk-free domain heuristics (`should_create_project_workspace`,
  `cve_min_severity_for_task`, `format_duration`, `temporary_cwd`) out of the
  `ui.py` god-class into a new `local_codex_lite/task_heuristics.py`.  `ui.py`
  re-imports them, so `from local_codex_lite.ui import ...` call sites and tests
  keep working; the logic is now unit-testable without Tkinter.  The new module
  imports `IntentDecision` only under `TYPE_CHECKING` to stay import-light.
- Extracted the GUI persistence (window geometry + task-history load/save and
  the de-dupe/cap transform) out of `ui.py` into a new
  `local_codex_lite/ui_state.py`.  The `CommandCenterUI` persistence methods are
  now thin delegators, and the file I/O is unit-tested without Tkinter.
- Extracted the workspace-routing decision out of `ui.py._prepare_workspace`
  into a pure `task_heuristics.plan_workspace` returning a `WorkspacePlan`
  (whether to use a project workspace and whether a fresh one must be created).
  The GUI method now just acts on the plan; the branching is unit-tested.

### Fixed
- Friendly Python-version guard in `local_codex_lite/__init__.py`: a 3.10
  interpreter now fails with a clear "requires Python 3.11+" message instead
  of a cryptic `ImportError: cannot import name 'UTC'` from a deep submodule.
- `recognize_intent` no longer assumes a non-empty capability list -- an empty
  registry returns a `needs_input` fallback instead of risking `IndexError`
  on `capabilities[0]`.

### Added
- `.gitlab-ci.yml` mirroring the GitHub Actions gates (stdlib smoke, then
  ruff lint + format-check + mypy + pytest with the 80% coverage floor) so
  pushes to the GitLab remote are actually verified.
- `tests/test_rich_compat.py` covering the stdlib `SimpleConsole`/`SimpleTable`
  fallback (rich_compat.py 43%->~95%).
- `tests/test_runner_apply.py`: an end-to-end `--apply` test (plan -> patch
  -> validate -> backup -> git apply -> result) driven by a content-aware
  stub LLM against a throwaway git repo -- the apply path had no direct
  coverage before.
- `tests/test_tool_registry_executors.py`: guards that every
  `ToolDefinition.executor` dotted-path still resolves to a real callable, so
  the descriptive metadata can't silently rot when a target is renamed.
- `tests/test_runner_repair_loop.py`: covers the runner's failure-recovery
  paths that the happy-path apply test does not reach -- the post-apply Python
  syntax gate restoring backups then repairing, `max_patch_attempts`
  exhaustion leaving the file pristine, and the patch-generation exception
  branch.
- `tests/test_task_heuristics.py`: direct unit coverage for the extracted
  task heuristics module (CVE severity selection, duration formatting,
  project-workspace routing, and the temporary-cwd context manager).
- `tests/test_ui_state.py`: covers the extracted GUI persistence helpers --
  geometry round-trip, task-history load/save, corrupt/non-list JSON handling,
  and the de-dupe/cap `push_task` transform.
- `skills/appsechub/` skill: read-only AppSecHub client + MCP wrapper that
  fetches and analyzes an application's issues (counts, severity mix, scanner
  breakdown, TruffleHog detector types, quality metrics).
- `docs/audit/AUDIT_AND_PLAN_20260606.md`: deep read-only audit and phased
  remediation plan.
- Full project documentation under `docs/`: overview, architecture
  (module map + run flow), complete CLI reference, configuration, the
  safety model, the evidence-first workflow (runs/CVE/TruffleHog),
  capability-plugin guide, development/CI, and troubleshooting (git-lock
  and venv-relocation recovery).  Linked from the README.

### Removed
- Pruned stale top-level files: `CHATGPT_HANDOFF.md` (self-marked as
  superseded by AGENTS.md), `GUI_ZERO_RESULTS_PLAYBOOK.md` (playbook for a
  bug fixed 2026-05-13), and the unreferenced `test_artifacts.ps1` smoke
  script.  Also cleared gitignored on-disk junk (stray `.coverage*`, old
  `output.cve-bin-tool.*.json` dumps, `generated_projects/` demo output).

### Changed
- Decomposed `planner.make_patch` (188 lines) into a 16-line dispatcher
  over two focused helpers -- `_make_runtime_fix_patch` (single-file
  traceback repair) and `_make_standard_patch` (context-variant retries) --
  so each generation strategy reads on its own.  Behaviour unchanged;
  covered by the existing planner retry/runtime-fix tests.
- Pinned `ruff==0.15.15` and `mypy==1.14.1` in **both** the `[dev]`
  extras and `.pre-commit-config.yaml` so local hooks and CI run
  identical versions.  Previously `ruff>=0.6` / `mypy>=1.10` floated to
  the latest release in CI while pre-commit pinned older revs, making
  lint results non-reproducible between the two.
- `cli.py` now declares `__all__` for the helpers re-exported from
  `cli_utils` / `runner`, so the ruff F401 + isort autofix can no longer
  silently strip the public/test re-exports.
- Extracted the 267-line argparse wiring out of `cli.py` into a new
  `local_codex_lite/cli_parser.py`; `cli.build_parser` is re-exported for
  backwards compatibility, so `cli.py` shrinks 900 -> 634 lines while the
  CLI surface lives in one focused module.  First step of the planned
  god-module split (`cli.py` / `ui.py` / `planner.py`).
- Extracted the four `review` diff/context helpers into a new
  `local_codex_lite/cli_review.py` (re-exported from `cli`), trimming
  `cli.py` further to ~566 lines.  Second step of the god-module split.
- Extracted the four `cmd_logs_*` handlers into a new
  `local_codex_lite/cli_logs.py` (re-exported from `cli`).  Third step of
  the god-module split; `cli.py` is now ~456 lines (from 900).
- Extracted the two `cmd_rag_*` handlers into a new
  `local_codex_lite/cli_rag.py` (re-exported from `cli`).  Fourth step of
  the god-module split; `cli.py` is now ~420 lines.
- Extracted the `init` / `status` / `config show` / `recognize` handlers
  into a new `local_codex_lite/cli_info.py` (re-exported from `cli`).
  Fifth step of the god-module split; `cli.py` is now ~395 lines, down
  from 900.  The remaining handlers are `main()` dispatch plus the
  LLM-backed `preview` / `ask` / `review` / `doctor` commands.
- Moved `cmd_review` next to its helpers in `cli_review.py` (re-exported
  from `cli`); `cli.py` is now ~326 lines, down from 900.  Added
  `tests/test_cli_reexports.py` asserting every name in `cli.__all__`
  stays importable, so the ruff autofix can never silently drop a
  `cli.*` re-export again.  Sixth step of the god-module split.
- Extracted the LLM-backed `cmd_preview` and `cmd_ask` handlers into a new
  `local_codex_lite/cli_query.py` (re-exported from `cli`).  Final step of
  the god-module split: `cli.py` is now ~238 lines (from 900) and is a
  thin dispatcher over the `cli_*` command modules.
- Added `RUF001`/`RUF002`/`RUF003` (ambiguous-unicode) to the ruff
  ignore list: Cyrillic literals in intent strings and tests are
  intentional for this Russian-language tool.

### Changed
- Wired the `SupportsChat` seam through the planner: `make_plan`,
  `make_patch`, `make_review`, `suggest_commands`, `repair_patch_with_error`
  and `revise_plan_with_assumptions` now take an optional keyword-only
  `client` argument (defaulting to a freshly constructed
  `OpenAICompatibleClient`).  This makes the planner's parse/return logic
  unit-testable with a conforming double instead of monkeypatching the
  module-level client class.  New `tests/test_planner_client_injection.py`;
  `planner.py` coverage 59%->62%.
- Added direct tests for the previously-uncovered command handlers:
  `tests/test_cli_rag.py` (cli_rag.py 28%->100%) and
  `tests/test_cli_dispatch.py` exercising the `cli.main()` routing
  (cli.py 45%->68%).  Total coverage 67%->68.5%.
- Documentation: AGENTS.md "Module architecture" now reflects the
  `cli_*` split (thin dispatcher + per-command modules) and the planner's
  injectable `SupportsChat` client seam.
- Added `tests/test_doctor_more.py` (doctor.py 55%->89%: LLM probe,
  run_doctor, preview_patch, run_full_doctor) and `tests/test_runner_more.py`
  (run_task --json redirect + unknown-profile early exit).  Total coverage
  68%->70%; CI/Makefile coverage floor ratcheted 60%->65%.
- Added `tests/test_runner_branches.py` for the clarification gate and the
  require-apply safety gate (runner.py 53%->59%).

### Fixed
- Made the `mypy` gate green for the first time: fixed all 55 type errors
  across 10 modules (42 source files now clean on `mypy==1.14.1`).  This
  covers the 10 errors introduced by the `SupportsChat` planner seam
  (internal helpers now accept the protocol, not the concrete client) plus
  ~45 pre-existing ones: `dict`-typed-as-`bool` result maps in runner,
  `object`->`int`/`str` casts in trufflehog, no-any-return casts in
  config/evidence_mode/llm_client, the `is_dataclass` instance narrowing in
  logging_utils, a robust `rich` optional-import shim (+`rich.*` added to
  the mypy ignore-missing-imports overrides), and targeted ignores for the
  Tkinter event-binding glue in ui.py.
- `rich_compat.SimpleConsole.print` no longer forwards rich-only
  keyword arguments (e.g. `highlight=`) to the builtin `print`; doing so
  raised `TypeError` whenever the optional `rich` extra was absent (the
  fallback path used by clean CI).
- Made the `cve-bin-tool` update-db path assertion platform-independent
  (it hard-coded the Windows separator and failed on POSIX runners).
- Cleared the ruff backlog: 149 autofixes plus manual `RUF005`,
  `RUF012`, `B011` and `F841` fixes; `ruff check` is now clean.

### Added
- `Makefile` giving Linux/macOS parity with the PowerShell helpers:
  `make check` runs the exact CI gate (lint + format-check + mypy + pytest
  with the 60% floor); plus `setup`/`lint`/`format`/`test`/`smoke`/`doctor`/
  `run`/`ask` targets.
- `local-codex-lite plugins list` -- shows every Capability the agent
  sees and its source (`builtin` or the entry-point name of the
  plugin that contributed it).  Supports `--plugins-only` and `--json`
  for scripting.  New module `local_codex_lite/plugins_cmd.py`, new
  `discover_capabilities_with_source()` / `CapabilitySource` API.
- `tools/stdlib_smoke.py`: zero-dependency smoke runner for the
  safety-critical core (`safety`, `patch_errors`, `capabilities`,
  `intent`, `targeting`, `path_filters`, `container_errors`, `prompts`,
  `evidence`, sample plugin).  Runs 59 tests via a tiny stdlib-only
  pytest shim with `tmp_path`/`monkeypatch` support, and is wired as a
  pre-job in `.github/workflows/ci.yml` so the heavy matrix only spins
  up when the core is green.
- `tools/proxy.ps1`, `tools/proxy.local.ps1.example` and
  `tools/pip.ini.template` plus a `setup.ps1 -WithPipIni` flag for
  developers who need `pip install` to route through a local proxy
  (e.g. v2rayN at `http://127.0.0.1:10809`).
- `local_codex_lite/runner.py`: dedicated module for the end-to-end
  `run_task` workflow.  `cli._run_task` is now a one-line re-export.
- `patcher.ApplyResult` dataclass replaces the
  `setattr(CompletedProcess, "git_apply_strategy", ...)` hack; the
  strategy is now a first-class field.
- Named `SCORE_*` constants in `workspace.py` for the file-ranking
  weights so every magic number has a documented purpose.
- `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- `pyproject.toml` now carries `license`, `authors`, `urls`, `keywords`
  and `classifiers`.
- `.pre-commit-config.yaml`: ruff + ruff-format + mypy + the standard
  pre-commit-hooks set.
- `intent.evidence.trufflehog.scan` now actually validates the
  `repo_url_or_file` input.  Without a URL or path it returns
  `can_do=needs_input` instead of silently routing through.
- CI: matrix gained `windows-latest / py3.12`; pip cache; coverage XML
  upload artifact; a no-LLM `cli-smoke` job (`doctor deps`,
  `config show`, `recognize`).
- `tests/test_intent.py` regression tests for `repo_url_or_file`
  detection (URL, `.txt`/`.list` repo files, Windows path).

### Changed
- `IntentDecision.required_inputs / missing_inputs / risks /
  matched_keywords` are now `tuple[str, ...]` instead of `list[str]` so
  the frozen dataclass is genuinely immutable.
- `safety.is_dangerous_command` switched from substring matching to
  word-boundary regexes.  `pytest --format=json`,
  `--shutdown-on-error`, `python -c "print(format(x))"` no longer trip
  the blocklist; `rm -rf`, `Remove-Item -Recurse`, `format c:`,
  `shutdown -r`, `curl | iex`, `Invoke-Expression` still do.
- `logging_utils.utc_timestamp()` now returns
  `YYYYMMDD-HHMMSS-uuuuuu-xxxxxx` (microseconds + 6 hex chars) so two
  runs in the same second do not share a run-dir.  Format stays
  lexicographically sortable.
- `logging_utils.sanitize_log_text` (moved from `cli_utils`) now does
  real regex masking of the secret value, not just a `<redacted>`
  prefix.  Url-embedded `user:pwd@host` and `Authorization: Basic ...`
  are also masked.
- `planner._log_llm_attempt` pushes `response_text` and `error` through
  `sanitize_log_text` before persisting to `events.jsonl`.
- `patcher.apply_patch` and `patcher.backup_paths` take an optional
  `run_dir` argument and, when given, write the patch file to
  `<run_dir>/patch.diff` and backups to `<run_dir>/backups/` instead of
  the shared `.local-codex-lite/patch.diff` / `backups/current/`.
  `cli._run_task` passes `run_dir` through, so concurrent runs no
  longer race and repair attempts do not clobber previous backups.
- `trufflehog.clone_repo` passes Basic auth via
  `-c http.extraHeader=Authorization: Basic <b64>` instead of embedding
  `user:token` in the URL.  The args list is redacted before any
  `CalledProcessError` is raised.
- `trufflehog._sanitize_error` also masks URL-embedded creds and
  `Authorization` headers as a defense in depth.
- `cli.py` lost ~370 lines: dead imports were removed (`AgentConfig`,
  `evidence_question_prompt`, `make_console`, `RankedWorkspaceFile`,
  `ensure_rag_provider_supported`, `retrieve_rag_context`,
  `PatchErrorClassification`, `append_jsonl`) and the `_run_task` body
  moved to `runner.py`.
- `args.exec` renamed to `args.execute` (via argparse `dest`); the
  `--exec` flag is unchanged and the `result["exec"]` key in
  `result.json` stays for backward compat.
- `config.example.yaml` now mirrors `AgentConfig` (added the `rag`
  section and `safety.max_patch_attempts`).
- pyproject `[tool.ruff]` now has a real rule selection
  (E/F/I/UP/B/SIM/W/RUF) and a paired `[tool.ruff.format]` block; mypy
  config gained `check_untyped_defs` / `no_implicit_optional` /
  `warn_redundant_casts`.  CI dropped `--ignore-missing-imports`.

### Fixed
- `tests/test_cli_evidence.py::test_resolve_cve_skill_script_raises_when_missing`
  now patches a stable module-level helper (`_candidate_exists`)
  instead of `Path.exists` which broke on Path subclass internals.
- `tests/test_config.py::test_save_and_load_config_roundtrip` builds
  the updated config via `model_copy(update=...)` so it survives a
  future `frozen=True` flip and also asserts the `rag` section round-
  trips (which catches `config.example.yaml` drift).

### Removed
- `local_codex_lite/prompts/prompts.md` (stray CLI command saved by
  accident).
- `tmp_review.diff` (untracked scratch file).
- The leaky substring rules `"format"` / `"shutdown"` in
  `safety.DISALLOWED_PATTERNS`; replaced by precise regexes.
- `setattr(subprocess.CompletedProcess, "git_apply_strategy", ...)` in
  `patcher.apply_patch`; replaced by `ApplyResult.strategy`.

### Repo hygiene
- New `.gitattributes` pins `*.py / *.md / *.toml / *.yaml / *.json` to
  LF and `*.ps1 / *.bat` to CRLF so the working tree stops accumulating
  spurious CRLF<->LF diffs.
- `local_codex_lite.egg-info/` confirmed not tracked; `.gitignore`
  already covers `*.egg-info/`.
- `.gitignore` now also covers `tools/proxy.local.ps1`.

### Added (CLI feature batch, post-cleanup)

A second wave of work landed after the stage 0-6 cleanup; each feature
is a self-contained commit with its own test file.  Per command:

- `--max-patch-attempts <N>`: one-shot override for
  `cfg.safety.max_patch_attempts` on a single `run` invocation.
- `doctor full`: aggregated health check that runs the core doctor +
  dependency probe + RAG fixture, then probes git / docker / 7z /
  cve-bin-tool on PATH.  Single command, one return code.
- `undo [--apply]`: restore workspace files from
  `<run_dir>/backups/`.  Dry-run by default; sensitive paths
  (.env / *.key / *secret*) are always skipped even with `--apply`.
- `logs diff <left> <right>`: side-by-side run comparison covering
  status / task / plan summary / patch error / evidence status /
  the symmetric set difference of artifacts.
- `evidence cve-scan-history [path]`: walks the given root (default
  `.local-codex-lite/runs`) for cve_summary.json files and prints a
  chronological table with critical/high/medium counts.
- `runs archive` / `runs prune`: zip every run-dir older than
  `--older-than N` (default 30) into `<run_id>.zip` next to it;
  `prune` also removes the source directory.  Dry-run by default.
- `runs export <run> [--out path]`: on-demand single-run zip,
  age-agnostic; intended for bug reports.  `--out` accepts a file
  path or a directory.
- `run --dry-run --json`: machine-readable dry-run output -- one
  JSON document on stdout with task / run_id / run_dir /
  selected_files / plan / result; every rich diagnostic line is
  redirected to stderr so the output can be piped into a JSON
  parser.
- `--profile <name>` on `run` / `preview` / `ask` / `review`: swaps
  `cfg.llm` for an entry in `cfg.llm_profiles` for the current
  invocation.  Unknown profile -> red diagnostic + non-zero exit.
- `replay <run_id> [--dry-run|--apply] [--profile X]`: re-runs a
  saved task by reading task.txt / plan.json / patch.diff from an
  existing run dir.  Reapplies the post-LLM pipeline
  (validate -> backup -> git apply -> AST gate) without contacting
  the model.  Useful for testing patcher/safety changes against
  historical positives and for air-gapped demos.
- `runs export` plus `replay` together let you ship a bug report
  zip and reproduce it on another machine offline.

### Added (safety + tooling)

- **AST gate after `git apply`**: every touched .py file is parsed
  with ast.parse; on SyntaxError the touched files are restored from
  `<run_dir>/backups/` and the patch is classified as
  `python_syntax_error` (retryable) so the repair loop kicks in.
  No syntactically broken Python ever 'commits' to the workspace.
- **multi-file runtime-fix context**: `RuntimeFixContext.secondary_files`
  carries up to two additional in-workspace .py files mentioned in
  the traceback as read-only context for the plan + patch prompts,
  so a small local model can reason about the call chain.  The patch
  remains single-file.
- **mutation testing via mutmut**: pyproject.toml ships a
  `[tool.mutmut]` config scoped to safety/patcher/patch_errors/
  llm_client.  `.github/workflows/mutmut.yml` runs on demand
  (`workflow_dispatch`) and weekly (Monday 04:00 UTC) and uploads
  the HTML report as a 30-day artifact.  PRs are deliberately not
  gated on the mutation score.
- **capability plugin discovery**: `discover_capabilities()` merges
  built-in capabilities with anything registered under the
  `local_codex_lite.capabilities` entry-point group.  Built-ins win
  on id collisions, so a third-party plugin cannot redefine
  safety-critical names like `run.apply`.  Misbehaving plugins
  (raising, wrong return type, non-Capability items in a list) are
  skipped with a warning -- a broken plugin must not take the agent
  down.

### Files added in this batch

- `local_codex_lite/runner.py` (stage 3b -- the run_task pipeline).
- `local_codex_lite/replay.py`, `local_codex_lite/runs_admin.py`,
  `local_codex_lite/undo.py`.
- `tests/test_cli_smoke.py`, `tests/test_llm_client_diff.py`,
  `tests/test_ui_utils.py`, `tests/test_undo.py`,
  `tests/test_logs_diff.py`, `tests/test_cve_scan_history.py`,
  `tests/test_runs_admin.py`, `tests/test_dry_run_json.py`,
  `tests/test_post_apply_syntax.py`, `tests/test_profile.py`,
  `tests/test_replay.py`, `tests/test_multifile_runtime_fix.py`,
  `tests/test_capabilities_discovery.py`.
- `tools/proxy.ps1`, `tools/proxy.local.ps1.example`,
  `tools/pip.ini.template`.
- `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`,
  `.pre-commit-config.yaml`, `.github/workflows/mutmut.yml`.

## [0.1.0] - prior to the cleanup sweep

Baseline state at commit `8ba6495 GUI improvements + tests`, before the
stages above started.  Original feature surface
(`run / preview / apply / exec`, evidence-first workflows,
`cve-bin-tool` skill, TruffleHog scan helper, Tkinter command center)
is documented in `README.md` and `AGENTS.md`.

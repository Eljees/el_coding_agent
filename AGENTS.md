# AGENTS.md — local-codex-lite

This file is the primary context document for any AI agent continuing work on this repository.
It defines project purpose, rules, architecture, and hard-won engineering lessons.

---

## Project purpose

`local-codex-lite` is a minimal local coding-agent MVP for Windows / PowerShell.

The agent talks only to a local OpenAI-compatible vLLM backend:

- Base URL: `http://localhost:8015/v1`
- Default model: `qwen25-coder-14b-awq`

The goal is to keep the project small, safe, readable, and extensible.

This is not an enterprise platform, not a web product, and not a multi-agent framework.

---

## Current state (updated 2026-06-12)

> Canonical change history lives in `CHANGELOG.md`.  The dated
> "session log" blocks in this file are point-in-time snapshots kept for
> reference, not the source of truth.

- Branch: `test/artifact-unpack`
- Last known clean test run: `838 passed` (2026-06-12; `testpaths = ["tests"]`; overall
  coverage 85.26%; runner.py 100%, cli.py 100%, cli_review.py 100%, planner.py 100%,
  runs_admin.py 98%, artifact_unpack.py 99%, ui_commands.py/ui_runners.py 100%;
  ui.py ~15% — remaining Tk widget/binding code)
- Skills tests (`skills/appsechub/test_appsechub_client.py`, 11 tests) are **intentionally**
  outside the default `testpaths` (they exercise the skill, not the package); run explicitly
  with `python -m pytest tests/ skills/`. Requires `requests` (now in `[dev]` extras).
- Toolchain pinned: `ruff==0.15.15`, `mypy==1.14.1` in both `[dev]` and
  `.pre-commit-config.yaml`; `ruff check`/`ruff format --check` are clean
- `cve-bin-tool` confirmed installed: `mode=executable`, `version=3.4`
- Real GUI-path CVE scan on `CYBERSEC-11195/contentreader-nls-16.9.0.14297-RedOS.rpm` reproduces
  non-zero: `total_findings=7`, `CRITICAL=2`, `HIGH=5`, `evidence_complete=true`
- GUI zero-results bug **fixed 2026-05-13**: `subprocess.run` in `cmd_evidence_cve_scan` now
  uses `capture_output=True` so output is routed through the GUI buffer
- `resolve_cve_skill_script` now raises `FileNotFoundError` with diagnostics instead of
  silently returning a non-existent path
- `_gzip_uncompressed_size` corrected for files > 4 GB (wraps uint32 → returns `None`)
- `detect_runtime_fix_context` now uses the first traceback candidate instead of refusing all
  cases with more than one matching file
- CI pipeline added: `.github/workflows/ci.yml` (ruff, mypy, pytest on Python 3.11 + 3.12)

### GUI improvements (2026-05-13, session 2)

`ui.py` was expanded from 676 → 1063 lines. All changes are backward-compatible.

- **Scrollbars**: all 5 `tk.Text` widgets now have linked `ttk.Scrollbar` (task input, evidence,
  IntentDecision JSON, command output, capability detail).
- **Window init**: `minsize(900, 600)`, `resizable(True, True)`, `update_idletasks()` before
  `mainloop()`.  Window geometry persists across sessions in `.local-codex-lite/ui_geometry.txt`.
- **Status bar**: packed at bottom of root (before main, so it stays visible).  Labels: cve-bin-tool
  version, LLM endpoint reachability, active workspace path — all probed in a daemon thread on startup.
- **Notebook tabs**: content reorganised into `ttk.Notebook` with two tabs:
  - **Agent** — the existing run/preview/apply workflow.
  - **Chat** — direct Q&A panel backed by `OpenAICompatibleClient`. Conversation history is kept
    in memory per session. Ctrl+Enter sends. Send button is disabled while the model is responding.
- **Task history dropdown**: `ttk.Combobox` above the task input. Tasks are saved to
  `.local-codex-lite/task_history.json` (up to 50 entries, deduplicated, most recent first)
  whenever Analyze / Preview / Apply / Exec is triggered. Selecting an entry restores the task text.
- **Progress bar + Stop**: indeterminate `ttk.Progressbar` starts when a background worker runs,
  stops when it finishes. Stop button sets `_stop_triggered` flag; `_finish_background` shows
  "Stopped by user." and skips the worker result.
- **Hotkeys**: F5 = Analyze, Ctrl+Enter = Preview, Ctrl+Shift+Enter = Apply (bound on `task_text`;
  return "break" so default newline is suppressed). Chat Ctrl+Enter remains isolated.
- **Export button**: saves current command output to a user-chosen file via `filedialog`.

### Verification commands

```powershell
python -m pytest -q
python -m local_codex_lite evidence cve-scan status
python -m local_codex_lite evidence cve-scan "D:\path\to\artifacts" --min-severity HIGH --format json,md,high-critical-md
python -m local_codex_lite evidence artifacts inspect --help
python -m local_codex_lite ui
```

---

## Recent structural changes

Changes made during the cleanup/improvement pass (tasks #1–#19):

- `commands.py` deleted — `SuggestedCommand` + `run_command` absorbed into `safety.py`
- `runtime_fix.py` deleted — `RuntimeFixContext` + `detect_runtime_fix_context` absorbed into `patcher.py`
- `cli.py` split from 1048 lines into `cli.py` + `cli_utils.py` + `cli_evidence.py`
- 2026-05-31 pass: `cli.py` further split 900 -> 238 lines into
  `cli_parser`/`cli_info`/`cli_logs`/`cli_rag`/`cli_query`/`cli_review`; planner gained
  the injectable `SupportsChat` client seam; ruff/mypy pinned in lockstep with
  pre-commit; CI gained a 60% coverage floor and a non-blocking ruff canary
- `intent.py` `_missing_inputs` refactored: no hardcoded capability IDs, driven by `required_inputs` tuples
- `capabilities.py` extended with `evidence.cve_scan` capability (12 capabilities total)
- `skills/cve-bin-tool/` added: `run_cve_scan.py` + `SKILL.md`
- `artifact_unpack.py` now detects `7z.exe` from standard Windows locations and explicit env overrides
- `cli_evidence.py` extended with `cmd_evidence_cve_scan` dispatching to the skill script
- `skills/cve-bin-tool/run_cve_scan.py` now scans with `--update never` by default and classifies incomplete evidence as `partial`/`failed`
- GUI CVE flow was validated against real artifact `CYBERSEC-11195/contentreader-nls-16.9.0.14297-RedOS.rpm`
- `ui.py` Apply button fix: preview-ready detection uses plain-text check, not Rich markup
- `llm_client.py` diff extraction fix: fence detected via `re.search` anywhere in LLM output, not just at position 0
- Deleted from git: `scan_runs/`, `tmp_trufflehog/`, `generated_projects/`, stray data files
- Documentation consolidated: `AGENTS.md`, `ARCHITECTURE.md`, `CHECKLIST.md`, `RISKS.md`, `NOTES.md` → single `AGENTS.md`

---

## Non-negotiable rules

- Do not break the current `run / preview / apply / exec` flow.
- Do not remove dry-run behavior.
- Do not apply patches unless `--apply` is explicitly used.
- Do not execute commands unless `--exec` is explicitly used.
- Do not remove workspace-only path checks.
- Do not remove sensitive-file blocking.
- Do not remove dangerous command blocking.
- Do not remove backup-before-apply behavior.
- Do not change the default model or base URL unless explicitly asked.
- Do not add web UI, GUI, multi-agent orchestration, or heavy frameworks unless explicitly asked.
- Keep changes small and reviewable.

---

## Safety model

The agent must be conservative by default.

It must block or avoid:

- path traversal;
- writing outside the workspace;
- reading secrets by default;
- exposing tokens, passwords, private keys, or credentials;
- destructive shell commands;
- network-dependent behavior unless explicitly part of the task;
- applying empty or unsafe patches.

Sensitive files include, but are not limited to:

- `.env`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`
- files containing `secret`, `token`, `password`, or `credential` in the name.

Never print secrets into logs, reports, prompts, or final summaries.

The CLI must call the same guarded executor that tests and GUI call.
A safety wrapper that exists but is bypassed by the main path is not safety.

---

## Evidence-first workflow

For security, SCA, TruffleHog, archive analysis, and scan-related work, always separate evidence from remediation.

Correct sequence:

1. Collect or load raw evidence.
2. Save raw evidence first.
3. Save summaries separately.
4. Classify errors or findings.
5. Decide whether a code/config fix is needed.
6. Generate a patch only after evidence is preserved.
7. Revalidate after applying changes.

Do not mix findings and fixes in one step.

Do not treat zero findings as proof of safety if:
- inventory is empty;
- scan failed or archive extraction failed;
- DB or tool snapshot drifted;
- evidence is incomplete;
- the model answered without grounded artifacts.

---

## Module architecture

### `local_codex_lite/cli.py`
Thin command dispatcher.  `main()` parses args (via `cli_parser.build_parser`) and routes
each top-level command to a handler in one of the focused `cli_*` modules below.  Keeps the
trivial `doctor`/`ui` handlers and re-exports every handler plus the historical `_underscore`
helpers -- pinned in `__all__` and guarded by `tests/test_cli_reexports.py` -- for backwards
compatibility.  Split from a 900-line god-module in the 2026-05-31 pass.

### `local_codex_lite/cli_parser.py`
All `argparse` wiring (`build_parser`) for the CLI surface, in one place.

### `local_codex_lite/cli_info.py`
`init`, `status`, `config show`, `recognize` handlers.

### `local_codex_lite/cli_logs.py`
`logs latest/tail/show/diff` handlers.

### `local_codex_lite/cli_rag.py`
`rag index` / `rag query` handlers.

### `local_codex_lite/cli_query.py`
LLM-backed `preview` (plan+patch) and `ask` (Q&A) handlers.

### `local_codex_lite/cli_review.py`
`review` handler plus its diff-acquisition / context-building helpers.

### `local_codex_lite/cli_utils.py`
Shared CLI utilities: `workspace_root`, console, output formatting helpers,
RAG context loading, evidence block loading, stdin evidence reader.

### `local_codex_lite/cli_evidence.py`
Evidence sub-commands: `json-compare`, `artifacts inspect`,
`trufflehog analyze/scan/compare`, `cve-scan`.
`cmd_evidence_cve_scan` delegates to `skills/cve-bin-tool/run_cve_scan.py` via subprocess.
`cve-scan` supports `status`, `install`, `update-db`, and `scan` actions.

### `local_codex_lite/llm_client.py`
OpenAI-compatible HTTP client: retries, heartbeat output, JSON extraction,
unified diff extraction, diff normalization, repair helpers.

### `local_codex_lite/planner.py`
Builds plans, patches, command suggestions, clarification-aware plan revision,
repair prompts with error-class input.
The LLM-calling entry points (`make_plan`, `make_patch`, `make_review`,
`suggest_commands`, `repair_patch_with_error`, `revise_plan_with_assumptions`) accept an
optional keyword-only `client` -- the `llm_client.SupportsChat` seam -- so they are
unit-testable with a fake client instead of monkeypatching the module-level class.

### `local_codex_lite/workspace.py`
Compact workspace context: file tree, ranked relevant files, selected snippets,
filtering of caches, secrets, and noisy folders.

### `local_codex_lite/safety.py`
Safety gates: workspace-only access, path traversal blocking, sensitive-file blocking,
dangerous shell command blocking.
Also hosts `SuggestedCommand` dataclass and `run_command()` (absorbed from deleted `commands.py`).

### `local_codex_lite/patcher.py`
Patch handling: diff validation, backup before apply, `git apply` through parent git-root.
Also hosts `RuntimeFixContext` dataclass and `detect_runtime_fix_context()` (absorbed from deleted `runtime_fix.py`).

### `local_codex_lite/intent.py`
Intent recognition: keyword scoring over capabilities, path/JSON extraction,
`_missing_inputs` validation (generic, no hardcoded capability IDs).

### `local_codex_lite/capabilities.py`
Capability registry: all supported capabilities with keywords, required inputs,
safety levels, and CLI equivalents.

### `local_codex_lite/artifact_unpack.py`
Archive inventory and extraction: zip/tar/gz/7z/rar/nupkg/jar/war/ear/whl/rpm.
Inventory-only mode is safe by default; extraction goes next to the source by default
or into an explicitly provided destination, while evidence metadata stays under the run folder.

### `local_codex_lite/doctor.py`
Checks config, workspace, git, model endpoint, and basic JSON sanity.

### `skills/`
Each skill is a self-contained subdirectory with `SKILL.md` (instructions + trigger phrases)
and optional script(s). Skills are discovered automatically by `skill_registry.py`.
When a skill uses frontmatter, `name` and `description` are the preferred metadata shown in the GUI skill list.
They are **not** called by the model — they are procedural scripts invoked by the CLI or
`cmd_evidence_*` handlers. Do not put untrusted code in skills.

Current skills:
- `artifact-unpack/` — documents archive inventory and extraction workflow for evidence-first analysis.
- `cve-bin-tool/` — installs, updates, and runs `cve-bin-tool`
on artifact directories with automatic archive unpacking and high/critical report generation.
Default CVE triage uses `--min-severity HIGH`; lower the threshold only when the task explicitly asks for a broader report.
`cve-bin-tool` `json` and `json2` outputs use different internal shapes and must not be parsed as if they were the same payload.
- `appsechub/` — read-only AppSecHub client (`appsechub_client.py`) + MCP wrapper
(`appsechub_mcp.py`) that fetch and analyze an application's issues: counts, severity
mix, scanner/source breakdown, TruffleHog detector types, and quality metrics. Auth via
`HUB_API_TOKEN`; base via `HUB_URL`. Never mutates AppSecHub state.

### Logging
Each run writes under `.local-codex-lite/runs/<timestamp>/`:
`task.txt`, `plan.json`, `selected_context.txt`, `patch.diff`, `commands.json`,
`result.json`, `events.jsonl`, `evidence/` subfolder.

---

## Patch repair classification

Patch failures are classified before a repair retry.

| Code | Repair action |
|---|---|
| `malformed_diff` | Ask for strict unified diff only |
| `context_mismatch` | Rebuild patch against current file contents |
| `file_already_exists` | Idempotent handling if file already matches |
| `path_mismatch` | Request repo-relative paths only |
| `unsafe_path` | Fail closed, no repair prompt |
| `empty_patch` | Reject no-op patch |
| `unknown` | Fallback repair path |

---

## CLI commands

```powershell
python -m pytest -q
python -m local_codex_lite doctor
python -m local_codex_lite config show
python -m local_codex_lite preview "task"
python -m local_codex_lite run "task" --dry-run
python -m local_codex_lite run "task" --apply
python -m local_codex_lite run "task" --apply --exec
python -m local_codex_lite logs latest
python -m local_codex_lite evidence json-compare left.json right.json
python -m local_codex_lite evidence artifacts inspect "D:\path\to\dir" --extract
python -m local_codex_lite evidence artifacts inspect "D:\path\to\dir" "D:\path\to\unpacked" --extract
python -m local_codex_lite evidence trufflehog analyze "D:\path\to\output"
python -m local_codex_lite evidence trufflehog scan --repo-url "https://gitlab.example.com/group/project.git"
python -m local_codex_lite evidence cve-scan status
python -m local_codex_lite evidence cve-scan install
python -m local_codex_lite evidence cve-scan update-db
python -m local_codex_lite evidence cve-scan "D:\path\to\artifacts" --install --min-severity HIGH
python -m local_codex_lite evidence cve-scan scan "D:\path\to\artifacts" --format json,md,high-critical-md --min-severity HIGH
python -m local_codex_lite evidence cve-scan "D:\already\extracted" --skip-unpack
python -m local_codex_lite ui
```

---

## Engineering rules

These rules were learned by building and breaking this agent. Apply them to every change.

**Start from the real runtime.**
Before designing behavior, confirm: cwd, git status, required CLIs, model endpoint reachability,
GUI startup, credential presence without printing.
`git apply` requires a git worktree -- no `.git` means apply cannot be trusted.

**State capabilities honestly.**
Capability = what the agent can route. Tool = deterministic callable code with schema + safety level.
Skill = procedural instructions with scripts. Shell command = risky fallback, not a tool.
Do not call keyword routing a tool system. Do not let the model call tools by emitting prose.

**Model output is untrusted input.**
Validate JSON shape; reject wrong types. Reject empty, no-op, comment-only patches.
Validate paths before apply. Classify failures before repair.
Rebuild repair prompts from current file contents, not model memory.
A model can correctly identify a bug but patch a line that does not exist.

**"Already exists" is not success.**
Before treating an existing file as applied: compare content, verify behavior,
run syntax check and smoke test, log the idempotency decision.

**Generated project routing must be intent-based.**
Route "create/build/new app/game" tasks to a dated generated workspace.
A filename hint should influence the output filename, not force editing an old file.

**Runtime fixes need a focused path.**
Detect traceback -> extract workspace file paths -> if exactly one Python file, use single-file repair
-> prompt with exact current content -> generate minimal diff -> re-run reproducer.
If repair repeats the same bad patch, stop and report.

**Prompting rules for small local models.**
Prefer: one target file, exact current content, explicit output schema, short repair prompts,
strict no-markdown instructions, bounded retries, deterministic fallback paths.
Avoid: broad workspace context for a one-file fix, long generic repair chains,
mixing plan/diff/command generation in one response.

**Validation ladder.**
Cheapest first: syntax check -> unit tests -> full suite -> CLI smoke -> GUI smoke ->
generated-app runtime test -> user scenario -> runtime-fix loop with traceback.

**Logging must explain decisions.**
Each run should record: selected files and why, workspace chosen and why, plan, patch,
validation errors, apply strategy, repair attempts, command suggestions and outputs,
evidence bundle status.

**GUI progress should stay visible.**
Long-running evidence workflows such as CVE scans must show visible progress or heartbeat updates in the GUI so the operator can tell the agent is still working.

**Red flags -- stop and redesign.**
- "It worked because the file already existed."
- "The model said it applied the patch."
- "The safety function exists, but the main path does not call it."
- "No findings means safe" without evidence completeness.
- "We can push later" while noisy artifacts are still tracked.

---

## What NOT to do next

- Do not turn this into a large framework.
- Do not add web UI, multi-agent orchestration, or heavy dependencies unless explicitly asked.
- Do not push `generated_projects/`, `scan_runs/`, `tmp_trufflehog/`, `.local-codex-lite/` to git.
- Do not change the default model or base URL without an explicit instruction.
- Do not remove any safety gate.
- Do not add skills that call external services or execute untrusted binaries.


---

## Post-cleanup state (2026-05-16+)

The stage 0-6 cleanup and the 14 feature commits that followed changed
several invariants the older sections above describe.  When the two
sections disagree, this one wins.

### New / renamed modules

- `local_codex_lite/runner.py` -- houses `run_task(task, args)`.
  `cli._run_task` is a one-line re-export, so tests / callers that
  imported `cli._run_task` keep working, but new code should
  monkey-patch `runner.*` rather than `cli.*`.
- `local_codex_lite/replay.py` -- `cmd_replay` re-runs a saved
  task/plan/patch without touching the LLM.
- `local_codex_lite/runs_admin.py` -- `cmd_runs_archive`,
  `cmd_runs_prune`, `cmd_runs_export` plus helpers
  `list_run_entries`, `select_for_archival`, `archive_run`.
- `local_codex_lite/undo.py` -- `cmd_undo` restores files from
  `<run_dir>/backups/` with sensitive-path filtering.
- `local_codex_lite/cli_evidence.py` gained
  `cmd_evidence_cve_scan_history` + `collect_cve_scan_history`.
- `local_codex_lite/patcher.py` gained `ApplyResult`,
  `SyntaxIssue`, `validate_python_syntax`,
  `restore_from_run_backups`, and the new `secondary_files` field on
  `RuntimeFixContext`.

### New CLI surface

```powershell
python -m local_codex_lite doctor full
python -m local_codex_lite run "<task>" --apply --max-patch-attempts 8
python -m local_codex_lite run "<task>" --dry-run --json
python -m local_codex_lite run "<task>" --profile fast
python -m local_codex_lite preview "<task>" --profile review
python -m local_codex_lite undo --run latest --apply
python -m local_codex_lite replay <run_id> --apply
python -m local_codex_lite logs diff <run_a> <run_b>
python -m local_codex_lite runs archive --older-than 30 --apply
python -m local_codex_lite runs prune --older-than 30 --apply
python -m local_codex_lite runs export <run> --out bug-report.zip
python -m local_codex_lite evidence cve-scan-history
```

### Safety: post-apply AST gate

After every successful `git apply`, `runner.run_task` walks the
touched `.py` files and runs `ast.parse` on each.  On
`SyntaxError` it restores the files from `<run_dir>/backups/`,
emits a `python_syntax_error` `PatchErrorClassification`, and
re-enters the repair loop (subject to `max_patch_attempts`).  No
syntactically invalid Python ever lands in the workspace.  The
same gate runs inside `replay --apply`.

### LLM profiles

`AgentConfig.llm_profiles: dict[str, LLMConfig]` (default `{}`)
holds named alternate endpoints.  `apply_profile(cfg, name)`
returns a `model_copy` with `cfg.llm` swapped for the chosen
profile; an unknown name raises `UnknownProfileError` listing the
available profile names.  Built-in `cfg.llm` stays the fallback
when `--profile` is not given.

### Capability plugin contract

Third-party packages can register additional capabilities under
entry-point group `local_codex_lite.capabilities`:

```toml
# in the plugin's pyproject.toml
[project.entry-points."local_codex_lite.capabilities"]
my_team_helpers = "my_team_lcl_plugins.capabilities:provide"
```

`provide()` returns a `Capability` or a list of them.  The CLI
(`cmd_recognize`) and the GUI use `discover_capabilities()` which
merges built-ins with plugin contributions.  **Built-ins always win
on id collisions** -- a plugin cannot redefine `run.apply`,
`run.exec`, `evidence.cve_scan`, etc.  Misbehaving plugins
(raising, wrong return type, non-`Capability` items) are skipped
with a `logging.warning` so a broken plugin cannot take the agent
down.

A ready-to-install reference implementation lives in
``examples/sample_capability_plugin/``: copy that directory, rename
the package, swap the ``Capability`` definitions, and ``pip install -e .``
in the same venv where ``local-codex-lite`` is installed.
``tests/test_sample_plugin_example.py`` keeps the example in sync
with the contract -- when the ``Capability`` dataclass changes, the
example breaks first.

To verify a plugin is actually picked up:

```powershell
python -m local_codex_lite plugins list
python -m local_codex_lite plugins list --plugins-only          # drops built-ins
python -m local_codex_lite plugins list --plugins-only --json   # for scripting
```

The text output prints a fixed-width table tagged with the source
(`builtin` vs the entry-point name).  If your plugin doesn't show up
there, ``recognize`` won't see it either -- so this is the first
diagnostic to run after a fresh ``pip install``.

### Mutation testing

`mutmut` is wired through `pyproject.toml` `[tool.mutmut]` against
`safety.py`, `patcher.py`, `patch_errors.py`, `llm_client.py`.
`.github/workflows/mutmut.yml` runs weekly (Monday 04:00 UTC) and
on `workflow_dispatch`.  PRs are **not** gated on the mutation
score.

### Things that moved or were dropped

- `cli.py` lost the `_run_task` body (moved to `runner.py`) and
  the dead imports (`AgentConfig`, `evidence_question_prompt`,
  `make_console`, `RankedWorkspaceFile`,
  `ensure_rag_provider_supported`, `retrieve_rag_context`,
  `PatchErrorClassification`, `append_jsonl`).
- `safety.DISALLOWED_PATTERNS` is now a tuple of
  human-readable summaries; the real check is a tuple of
  pre-compiled regexes (`_DANGEROUS_COMMAND_PATTERNS`) using
  word boundaries.
- `IntentDecision` sequence fields are `tuple[str, ...]`, not
  `list[str]`.
- `apply_patch` returns an `ApplyResult` dataclass with
  `returncode`/`stdout`/`stderr`/`strategy` instead of a
  `subprocess.CompletedProcess` decorated by `setattr`.
- Patch files and backups live under `<run_dir>/` (`patch.diff`,
  `backups/<rel>`) instead of the shared
  `.local-codex-lite/patch.diff` and `backups/current/`.
- `logging_utils.utc_timestamp()` returns
  `YYYYMMDD-HHMMSS-uuuuuu-xxxxxx` (microseconds + 6 hex chars)
  so two concurrent runs cannot collide.
- `args.exec` was renamed to `args.execute` (argparse `dest`);
  the `--exec` flag is unchanged.
- `result["exec"]` in `result.json` is kept for downstream
  compatibility.

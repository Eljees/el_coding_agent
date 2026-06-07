# Architecture

## Package layout

The agent is the `local_codex_lite/` package. The CLI was split out of a former
900-line `cli.py` god-module into a thin dispatcher plus focused per-command
modules.

### CLI layer

| Module | Responsibility |
|--------|----------------|
| `cli.py` | Thin dispatcher: `main()` parses args and routes each command. Re-exports every handler + the historical `_underscore` helpers (pinned in `__all__`, guarded by `tests/test_cli_reexports.py`). |
| `cli_parser.py` | All `argparse` wiring (`build_parser`). |
| `cli_info.py` | `init`, `status`, `config show`, `recognize`. |
| `cli_logs.py` | `logs latest/tail/show/diff`. |
| `cli_rag.py` | `rag index`, `rag query`. |
| `cli_query.py` | LLM-backed `preview` (plan+patch) and `ask` (Q&A). |
| `cli_review.py` | `review` plus its diff-acquisition / context helpers. |
| `cli_evidence.py` | `evidence` sub-commands: json-compare, artifacts inspect, trufflehog, cve-scan. |
| `cli_utils.py` | Shared helpers: `workspace_root`, console, output formatting, RAG/evidence loading. |
| `runner.py` | The end-to-end `run` workflow (`run_task` / `_run_task_body`). |

### Core layer

| Module | Responsibility |
|--------|----------------|
| `planner.py` | Builds plans, patches, command suggestions, plan revision and repair prompts. LLM entry points (`make_plan`, `make_patch`, `make_review`, ...) accept an optional `client` — the `llm_client.SupportsChat` seam — for testability. |
| `llm_client.py` | OpenAI-compatible HTTP client (retries, heartbeat, JSON/diff extraction, repair). Defines the `SupportsChat` protocol. |
| `workspace.py` | Compact workspace context: file tree, ranked relevant files, filtering of caches/secrets. |
| `safety.py` | Safety gates + `SuggestedCommand` + `run_command()`. |
| `patcher.py` | Diff validation, backup-before-apply, `git apply` via the parent git root; `RuntimeFixContext`. |
| `intent.py` | Intent recognition (keyword scoring over capabilities). |
| `capabilities.py` | Capability registry + `entry_points` discovery. |
| `doctor.py` | Health checks: config, workspace, git, LLM endpoint, dependencies, RAG. |
| `artifact_unpack.py` | Archive inventory/extraction (zip/tar/gz/7z/rar/rpm/...). |
| `trufflehog.py` | TruffleHog scan + report parsing. |
| `rag.py` | Retrieval-augmented context (keyword provider by default). |
| `evidence.py` / `evidence_mode.py` | Evidence bundles + status files. |
| `logging_utils.py` | Per-run logging under `.local-codex-lite/runs/<ts>/`. |
| `lessons.py` | Lessons memory: curated + learned pitfalls injected into prompts. |
| `replay.py` / `undo.py` / `runs_admin.py` | Re-run a saved task, restore from backups, manage the runs lifecycle. |
| `ui.py` | Optional Tkinter command center (GUI). |

## How a `run` flows

1. `runner._run_task_body` resolves the workspace and loads config.
2. Evidence text (tracebacks/logs) is loaded; a runtime-fix context is detected.
3. Files are ranked and selected (`workspace.py`).
4. `planner.make_plan` asks the LLM for a plan; clarification is handled.
5. On `--dry-run` it stops after preview.
6. The `require_apply_flag` safety gate blocks writes unless `--apply`.
7. `planner.make_patch` produces a unified diff; `patcher` validates, backs up
   and applies it; a post-apply AST gate rejects syntactically broken Python.
8. Suggested commands run only with `--exec`.
9. Everything is logged + bundled as evidence under the run directory.

## Lessons memory

A weak local model repeats the same mistakes, so `lessons.py` feeds it short
"known pitfalls" reminders. Two sources combine:

- **Curated** (`CURATED_PITFALLS`): hand-written rakes keyed by trigger keywords
  (tkinter options, invented imports, mutable default args, missing `encoding=`,
  Unix-only shell tooling, indentation, f-string quote clashes). A pitfall fires
  when any keyword appears in `task.lower()`.
- **Learned** (`.local-codex-lite/lessons.jsonl`): one record per
  error-then-recovery. `runner._run_task_body` calls `record_lesson(...)` **only**
  when a patch attempt failed and a later attempt then succeeded, persisting the
  last caught error's code + detail. Records are deduped by a normalized
  signature and capped. A learned lesson resurfaces when a future task shares a
  significant word with the failed task.

A third, unconditional source is the user's own `AGENT_RULES.md` in the
workspace root: bullet lines become rules the model must always follow
(`load_user_rules` / `user_rules_block`; manage with `local-codex-lite rules
init` / `rules show`, see [configuration](configuration.md#user-rules-agent_rulesmd)).

`planner.make_plan` and `make_patch` (the standard, non-runtime-fix paths) build
`guardrails_block(workspace_root, task)` — user rules first, then the relevant
lessons — and pass it to `plan_prompt` / `patch_prompt` as the optional
`pitfalls` block. The lessons part is intentionally short (max three bullets) —
long context hurts small models. Inspect or reset the learned ledger with
`local-codex-lite lessons list` / `lessons clear`.

## The LLM seam

`llm_client.SupportsChat` is a `runtime_checkable` protocol with a single
`chat(...)` method. Both the real `OpenAICompatibleClient` and test doubles
satisfy it, so planner logic is unit-testable without a live endpoint
(`tests/test_planner_client_injection.py`).

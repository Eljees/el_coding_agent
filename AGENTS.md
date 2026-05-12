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

## Recent structural changes

Changes made during the cleanup/improvement pass (tasks #1–#19):

- `commands.py` deleted — `SuggestedCommand` + `run_command` absorbed into `safety.py`
- `runtime_fix.py` deleted — `RuntimeFixContext` + `detect_runtime_fix_context` absorbed into `patcher.py`
- `cli.py` split from 1048 lines into `cli.py` + `cli_utils.py` + `cli_evidence.py`
- `intent.py` `_missing_inputs` refactored: no hardcoded capability IDs, driven by `required_inputs` tuples
- `capabilities.py` extended with `evidence.cve_scan` capability (12 capabilities total)
- `skills/cve-bin-tool/` added: `run_cve_scan.py` + `SKILL.md`
- `cli_evidence.py` extended with `cmd_evidence_cve_scan` dispatching to the skill script
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
Main CLI entry point. Loads config, indexes workspace, ranks files, requests plan and patch,
validates, previews, applies with `--apply`, executes with `--exec`, writes logs.

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
They are **not** called by the model — they are procedural scripts invoked by the CLI or
`cmd_evidence_*` handlers. Do not put untrusted code in skills.

Current skills:
- `artifact-unpack/` — documents archive inventory and extraction workflow for evidence-first analysis.
- `cve-bin-tool/` — installs, updates, and runs `cve-bin-tool`
on artifact directories with automatic archive unpacking and high/critical report generation.

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

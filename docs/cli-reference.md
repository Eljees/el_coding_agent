# CLI reference

Invoke as `python -m local_codex_lite <command>` (or the installed
`local-codex-lite` script). Global flags: `--profile <name>` selects an
`llm_profiles` entry; `--max-patch-attempts <n>` overrides the safety budget.

## Core workflow

| Command | Description |
|---------|-------------|
| `run "<task>"` | The full loop. Flags: `--dry-run`, `--apply`, `--exec`, `--assume-clarification`, `--evidence-file <p>` (repeatable), `--evidence-stdin`, `--json` (machine-readable, dry-run only). |
| `preview "<task>"` | Plan + patch + preview, never writes. `--rag`, `--evidence-file`, `--evidence-stdin`. |
| `ask "<question>"` | Direct Q&A against the model. `--rag`, `--evidence-file`, `--evidence-stdin`. |
| `review` | Read-only code review of a diff. `--base`, `--head`, `--staged`, `--diff-file`, `--diff-stdin`. |

## Inspection & setup

| Command | Description |
|---------|-------------|
| `init` | Create `.local-codex-lite/config.yaml` from defaults. |
| `status` | Show workspace, config path, and the configured LLM endpoint. |
| `recognize "<task>"` | Print the intent decision (routing only, no LLM). |
| `doctor` | Health check: config, workspace, git, LLM endpoint, JSON sanity. |
| `doctor deps` | Runtime dependency probe (no network). |
| `doctor rag` | RAG fixture probe. |
| `doctor full` | Aggregate doctor + deps + rag + optional tool probes. |
| `config show` | Print the effective, redacted config as JSON. |
| `ui` | Launch the optional Tkinter command center. `--autoclose-ms`. |

## Logs & run lifecycle

| Command | Description |
|---------|-------------|
| `logs latest` | Show the most recent run's events. |
| `logs tail [--run <id>] [--lines N]` | Tail a run's `events.jsonl`. |
| `logs show <run_id>` | Print a run summary. |
| `logs diff <left> <right>` | Side-by-side comparison of two runs. |
| `runs archive [--older-than N] [--apply]` | Archive old runs (dry-run by default). |
| `runs prune [--older-than N] [--apply]` | Archive + delete old runs. |
| `runs export [--run <id>] [--out <path>]` | Zip a single run (bug-report friendly). |
| `replay <run_id> [--dry-run] [--apply]` | Re-apply a saved task without calling the LLM. |
| `undo [--run <id>] [--apply]` | Restore workspace files from a run's `backups/`. |

## RAG

| Command | Description |
|---------|-------------|
| `rag index [--rebuild]` | Build the retrieval index for the workspace. |
| `rag query "<query>" [--top-k N]` | Query the index. |

## Capability plugins

| Command | Description |
|---------|-------------|
| `plugins list [--plugins-only] [--json]` | Show every capability the agent sees and its source (`builtin` or the contributing plugin). |

## Evidence & security tooling

| Command | Description |
|---------|-------------|
| `evidence json-compare <left> <right> [--out]` | Diff two JSON artifacts. |
| `evidence artifacts inspect <input_root> [--extract] [--extract-to] [--max-depth] [--max-files] [--max-total-bytes]` | Inventory / extract archives. |
| `evidence trufflehog scan` | Run TruffleHog through Docker (GitLab repos). `--repo-url` (repeatable), `--repo-file`, `--git-user`, `--git-token`, `--image`, `--depth`, `--keep-clones`. |
| `evidence trufflehog analyze <input_root> [--out]` | Analyze TruffleHog output. |
| `evidence trufflehog compare <left> <right> [--out]` | Compare two TruffleHog runs. |
| `evidence cve-scan <status|install|update-db|scan|input_root> [...]` | `cve-bin-tool` runner. `--extract-to`, `--output-dir`, `--install`, `--update-db`, `--skip-unpack`, `--offline`, `--min-severity`, `--format`. |
| `evidence cve-scan-history [path]` | List past `cve-bin-tool` scans by walking a tree. |

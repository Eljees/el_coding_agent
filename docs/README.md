# local-codex-lite documentation

A minimal, **local** coding-agent MVP for Windows / PowerShell that talks only
to a local OpenAI-compatible vLLM backend. Safe by default, evidence-first,
small and readable.

## Contents

| Doc | What it covers |
|-----|----------------|
| [Overview](overview.md) | What the project is, its philosophy and priorities |
| [Architecture](architecture.md) | Module map and how a run flows end to end |
| [CLI reference](cli-reference.md) | Every command and flag (auto-generated from the parser by `scripts/gen_cli_reference.py`) |
| [Configuration](configuration.md) | `config.yaml`, LLM profiles, workspace/safety/RAG knobs |
| [Safety model](safety.md) | The non-negotiable safety gates |
| [Evidence-first workflow](evidence.md) | Runs, evidence bundles, CVE & TruffleHog scanning |
| [Capability plugins](plugins.md) | Extending the agent via `entry_points` |
| [Development & CI](development.md) | Setup, the quality gates, the Makefile, releasing |
| [Troubleshooting](troubleshooting.md) | Common problems (git locks, venv relocation, endpoints) |
| [Audit notes](audit/) | Point-in-time project audits and improvement plans (latest first; older ones live in `audit/archive/`) |

## Where to start

New to the project? Read in this order:

1. [Overview](overview.md) — what this is, what it refuses to be, and why.
2. [Safety model](safety.md) — the rules everything else is built around.
3. The 30-second tour below, then the [CLI reference](cli-reference.md) as needed.
4. [Configuration](configuration.md) — once the defaults stop being enough.
5. [Architecture](architecture.md) — when you want to read or change the code.
6. [Development & CI](development.md) — before you send a change.

Dip into the [evidence-first workflow](evidence.md), [capability plugins](plugins.md)
and [troubleshooting](troubleshooting.md) pages when the topic comes up; the
[audit notes](audit/) are background reading, not required.

## 30-second tour

```powershell
.\scripts\setup.ps1                              # create .venv, install -e ".[dev]"
.\scripts\doctor.ps1                             # check config, git, the LLM endpoint
python -m local_codex_lite run "fix the bug in foo.py" --dry-run
python -m local_codex_lite run "fix the bug in foo.py" --apply
```

Nothing is written without `--apply`; no command runs without `--exec`.

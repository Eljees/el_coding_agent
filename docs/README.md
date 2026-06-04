# local-codex-lite documentation

A minimal, **local** coding-agent MVP for Windows / PowerShell that talks only
to a local OpenAI-compatible vLLM backend. Safe by default, evidence-first,
small and readable.

## Contents

| Doc | What it covers |
|-----|----------------|
| [Overview](overview.md) | What the project is, its philosophy and priorities |
| [Architecture](architecture.md) | Module map and how a run flows end to end |
| [CLI reference](cli-reference.md) | Every command and flag |
| [Configuration](configuration.md) | `config.yaml`, LLM profiles, workspace/safety/RAG knobs |
| [Safety model](safety.md) | The non-negotiable safety gates |
| [Evidence-first workflow](evidence.md) | Runs, evidence bundles, CVE & TruffleHog scanning |
| [Capability plugins](plugins.md) | Extending the agent via `entry_points` |
| [Development & CI](development.md) | Setup, the quality gates, the Makefile, releasing |
| [Troubleshooting](troubleshooting.md) | Common problems (git locks, venv relocation, endpoints) |

## 30-second tour

```powershell
.\scripts\setup.ps1                              # create .venv, install -e ".[dev]"
.\scripts\doctor.ps1                             # check config, git, the LLM endpoint
python -m local_codex_lite run "fix the bug in foo.py" --dry-run
python -m local_codex_lite run "fix the bug in foo.py" --apply
```

Nothing is written without `--apply`; no command runs without `--exec`.

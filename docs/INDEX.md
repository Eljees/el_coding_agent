# Documentation index — local-codex-lite

Quick reference to every doc file in this repository.

## Getting started

| Document | What it covers |
|---|---|
| [README (root)](../README.md) | 30-second tour, install, first run |
| [docs/README.md](README.md) | Docs directory index and links |
| [docs/overview.md](overview.md) | Project philosophy, goals, non-goals |
| [docs/configuration.md](configuration.md) | Full `config.yaml` reference: LLM, workspace, safety, RAG, profiles |
| [docs/troubleshooting.md](troubleshooting.md) | Git lock-files, venv relocation, unreachable endpoints |

## CLI reference

| Document | What it covers |
|---|---|
| [docs/cli-reference.md](cli-reference.md) | Auto-generated command reference (run, ask, preview, review, evidence, rag, doctor, …) |

## Architecture & internals

| Document | What it covers |
|---|---|
| [docs/architecture.md](architecture.md) | Module map, run flow, planner → patcher → apply pipeline |
| [docs/safety.md](safety.md) | Non-negotiable safety gates (path traversal, shell commands, secrets) |
| [docs/evidence.md](evidence.md) | Run directories, evidence bundles, CVE/TruffleHog/artifact workflows, post-apply smoke testing |
| [docs/plugins.md](plugins.md) | Writing and registering capability plugins (skills) |

## Development & operations

| Document | What it covers |
|---|---|
| [docs/development.md](development.md) | Setup, virtual env, Makefile targets, CI gates, releasing |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](../SECURITY.md) | Security policy and responsible disclosure |
| [CHANGELOG.md](../CHANGELOG.md) | Version history and change log |
| [AGENTS.md](../AGENTS.md) | AI-agent context: project rules, architecture, metrics, hard-won lessons |

## Audit history

| Document | What it covers |
|---|---|
| [docs/audit/AUDIT_20260606_v3.md](audit/AUDIT_20260606_v3.md) | Latest point-in-time audit (2026-06-06, after phases 0-4) |
| [docs/audit/archive/](audit/archive/) | Previous audit versions |

## Skills

| Skill | Document |
|---|---|
| AppSecHub | [skills/appsechub/SKILL.md](../skills/appsechub/SKILL.md) |
| Artifact unpacking | [skills/artifact-unpack/SKILL.md](../skills/artifact-unpack/SKILL.md) |
| CVE scanning | [skills/cve-bin-tool/SKILL.md](../skills/cve-bin-tool/SKILL.md) |

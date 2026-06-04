# Overview

## What it is

`local-codex-lite` is a small command-line coding agent. Given a task in plain
language it inspects the current workspace, asks a **local** LLM for a plan,
generates a unified diff, validates and previews it, and only applies it when
you explicitly ask. It also bundles security tooling: CVE scanning
(`cve-bin-tool`), secret scanning (TruffleHog), and archive/artifact unpacking.

The agent talks **only** to a local OpenAI-compatible vLLM backend:

- Base URL: `http://localhost:8015/v1`
- Default model: `qwen25-coder-14b-awq`

It is intentionally **not** an enterprise platform, web product, or multi-agent
framework.

## Priorities (in order)

1. **Safety first.** Workspace-only file access, sensitive-file blocking,
   dangerous-command blocking, backup-before-apply, patches only with `--apply`,
   commands only with `--exec`, dry-run is sacred. See [safety](safety.md).
2. **Evidence-first.** Proof (CVE / TruffleHog / artifacts) is stored separately
   from fixes under `runs/<timestamp>/evidence/`. See [evidence](evidence.md).
3. **Small and readable.** "Keep changes small and reviewable." No heavy
   frameworks; new behaviour ships behind explicit flags.
4. **Local and private.** No cloud calls; everything runs against your own vLLM.

## The core loop

```
task --> inspect workspace --> rank files --> ask LLM for a plan
     --> generate unified diff --> validate / normalize / repair
     --> preview --> (--apply) apply with backup --> (--exec) run suggested commands
     --> write logs + evidence under .local-codex-lite/runs/<timestamp>/
```

## Who it is for

Developers running a local code model who want a auditable, safety-gated agent
that edits a single workspace and keeps a full paper trail of every run.

# Capability plugins

The agent's capabilities (the things `intent` can route a task to) are
discoverable via Python `entry_points`, so you can add new ones without touching
the core. Built-ins always take priority; a misbehaving plugin is skipped with a
warning and can never take the agent down.

## Inspecting capabilities

```
python -m local_codex_lite plugins list            # all capabilities + source
python -m local_codex_lite plugins list --plugins-only   # only entry-point ones
python -m local_codex_lite plugins list --json     # machine-readable
```

The `source` column is `builtin` or the entry-point name of the contributing
plugin.

## Contributing a capability

Register an entry point in the plugin's `pyproject.toml` under the
capability group the agent discovers. A capability declares keywords, required
inputs, a safety level and a CLI equivalent. See
[`examples/sample_capability_plugin`](../examples/sample_capability_plugin) for a
paste-able reference.

## Where new integrations should live

Keep the core small. External integrations — containers, email, browser
automation, file downloads — belong in **plugins / MCP connectors**, not the
core package. Suggested fits:

| Need | Option |
|------|--------|
| Containers & container networks | Docker / Kubernetes / Podman MCP (e.g. the `el-sca-docker` server already wired for scans) |
| Email (send scan reports) | Gmail / MS365 / generic IMAP-SMTP MCP |
| Browser automation | Claude in Chrome, or Playwright / Puppeteer MCP |
| File downloads | a fetch/download MCP or a small `requests`-based capability |

This preserves the "small, safe, readable" core while letting power users bolt
on heavier capabilities behind the plugin boundary.

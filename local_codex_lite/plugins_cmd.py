"""``local-codex-lite plugins list`` -- discoverability for capability plugins.

Prints every Capability the agent currently sees, tagged with where it
came from (``builtin`` or the entry-point name of the plugin that
contributed it).  Handy after ``pip install`` of a third-party plugin
to verify the agent actually picked it up.
"""

from __future__ import annotations

import argparse
import json

from .capabilities import discover_capabilities_with_source


def _render_text(entries: list[tuple]) -> str:
    """Format ``(source, capability)`` rows as a fixed-width table."""
    rows = [(src.kind, src.name or "-", cap.id, cap.title) for src, cap in entries]
    header = ("source", "plugin", "id", "title")
    widths = [
        max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(header)
    ]
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    out = [fmt.format(*header), fmt.format(*("-" * w for w in widths))]
    for r in rows:
        out.append(fmt.format(*r))
    return "\n".join(out)


def _entries_as_json(entries: list[tuple]) -> str:
    payload = [
        {
            "source": {"kind": src.kind, "name": src.name},
            "capability": {
                "id": cap.id,
                "title": cap.title,
                "safety_level": cap.safety_level,
                "requires_apply": cap.requires_apply,
                "requires_exec": cap.requires_exec,
                "required_inputs": list(cap.required_inputs),
            },
        }
        for src, cap in entries
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False)


def cmd_plugins_list(args: argparse.Namespace) -> int:
    """Print discovered capabilities.

    Flags:
        --plugins-only   show only entry-point contributed capabilities
                         (drops the built-ins so an empty result clearly
                         means "no plugins are installed").
        --json           emit a machine-readable JSON document instead of
                         the text table.
    """
    entries = discover_capabilities_with_source()
    if getattr(args, "plugins_only", False):
        entries = [(s, c) for s, c in entries if s.kind == "plugin"]

    if getattr(args, "json_output", False):
        print(_entries_as_json(entries))
        return 0

    if not entries:
        print("(no capabilities found)")
        return 0
    print(_render_text(entries))
    n_plugin = sum(1 for s, _ in entries if s.kind == "plugin")
    n_builtin = sum(1 for s, _ in entries if s.kind == "builtin")
    print()
    print(f"{len(entries)} total ({n_builtin} built-in, {n_plugin} from plugins)")
    return 0

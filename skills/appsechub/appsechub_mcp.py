#!/usr/bin/env python3
"""AppSecHub MCP server (stdio) for local-codex-lite.

Thin Model Context Protocol wrapper around ``appsechub_client``. Mirrors the
shape of the existing ``el-sca-docker`` MCP server: each tool is a small,
typed function that delegates to the data layer.

Run:
    pip install "mcp[cli]"            # one-time, in the agent environment
    HUB_API_TOKEN=... python appsechub_mcp.py

Register in the agent's MCP config (stdio), e.g.:
    {
      "mcpServers": {
        "appsechub": {
          "command": "python",
          "args": ["skills/appsechub/appsechub_mcp.py"],
          "env": { "HUB_API_TOKEN": "${HUB_API_TOKEN}",
                   "HUB_URL": "https://appsechub.ssdlc.soc.rt.ru/hub/rest" }
        }
      }
    }

All tools are read-only: they fetch and aggregate issues, never mutate state.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Allow running both as a module and as a loose script next to the client.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import appsechub_client as hub

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "The 'mcp' package is required to run the AppSecHub MCP server.\n"
        'Install it with:  pip install "mcp[cli]"\n'
        f"Import error: {exc}"
    )

mcp = FastMCP("appsechub")


@mcp.tool()
def parse_app_url(url: str) -> int:
    """Extract the numeric application id from an AppSecHub URL (or bare id).

    Example: '.../#/appprofile/89/issues' -> 89.
    """
    return hub.parse_app_url(url)


@mcp.tool()
def list_scanners(with_issue: bool = False) -> list[dict[str, Any]]:
    """List available scanner tools. Set with_issue=True for only scanners that produced issues."""
    return hub.list_scanners(with_issue=with_issue)


@mcp.tool()
def get_app_summary(app: str) -> dict[str, Any]:
    """Severity rollup for one application. 'app' may be an id or an AppSecHub URL."""
    return hub.get_app_summary(hub.parse_app_url(app))


@mcp.tool()
def list_issues(
    app: str,
    source: str | None = None,
    severities: list[str] | None = None,
    statuses: list[str] | None = None,
    types: list[str] | None = None,
    max_items: int = 1000,
) -> dict[str, Any]:
    """Fetch brief issues for an application with optional filters.

    'app' may be an id or URL. 'source' is the scanner (e.g. 'trufflehog').
    Returns {count, issues}. Use breakdown_issues for aggregated views.
    """
    rows = hub.list_issues(
        hub.parse_app_url(app),
        source=source,
        severities=severities,
        statuses=statuses,
        types=types,
        max_items=max_items,
    )
    return {"count": len(rows), "issues": rows}


@mcp.tool()
def breakdown_issues(
    app: str,
    source: str | None = None,
    by: str = "source,severity,type",
    max_items: int = 5000,
) -> dict[str, Any]:
    """Aggregate an application's issues.

    Returns counts grouped by the requested fields, a TruffleHog detector-type
    breakdown, and lightweight quality metrics (severity mix, FP-like rate).
    'app' may be an id or URL; 'source' optionally restricts to one scanner.
    """
    app_id = hub.parse_app_url(app)
    rows = hub.list_issues(app_id, source=source, max_items=max_items)
    fields = [b.strip() for b in by.split(",") if b.strip()]
    return {
        "app_id": app_id,
        "total_fetched": len(rows),
        "breakdown": hub.breakdown(rows, by=fields),
        "trufflehog_types": hub.trufflehog_types(rows),
        "quality": hub.quality_metrics(rows),
    }


@mcp.tool()
def compare_scans(
    app: str,
    old_scan: int,
    new_scan: int,
    source: str | None = None,
    max_items: int = 5000,
) -> dict[str, Any]:
    """Delta of issues between two scans of an application.

    Returns added (new findings), removed (fixed / no longer detected), and
    unchanged counts plus per-severity breakdowns and the full added/removed
    lists. 'app' may be an id or URL; 'source' optionally restricts to one
    scanner (e.g. 'trufflehog').
    """
    return hub.compare_scans(
        hub.parse_app_url(app),
        old_scan,
        new_scan,
        source=source,
        max_items=max_items,
    )


if __name__ == "__main__":
    mcp.run()

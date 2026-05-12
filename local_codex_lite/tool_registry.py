from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: dict[str, Any]
    executor: str
    safety_level: str
    requires_exec: bool


def default_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="shell.run",
            description="Run one validated local shell command in the active workspace.",
            schema={
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "timeout": {"type": "integer", "default": 120},
                },
                "required": ["cmd"],
                "additionalProperties": False,
            },
            executor="local_codex_lite.safety.run_command",
            safety_level="guarded",
            requires_exec=True,
        ),
        ToolDefinition(
            name="logs.latest",
            description="Read the latest local run log from .local-codex-lite/runs.",
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            executor="local_codex_lite.cli.cmd_logs_latest",
            safety_level="safe",
            requires_exec=False,
        ),
        ToolDefinition(
            name="evidence.json_compare",
            description="Compare two JSON artifacts and write a separate summary.",
            schema={
                "type": "object",
                "properties": {
                    "left": {"type": "string"},
                    "right": {"type": "string"},
                    "out": {"type": "string"},
                },
                "required": ["left", "right"],
                "additionalProperties": False,
            },
            executor="local_codex_lite.cli.cmd_evidence_json_compare",
            safety_level="safe",
            requires_exec=False,
        ),
        ToolDefinition(
            name="evidence.artifacts.inspect",
            description="Inventory archive artifacts and optionally extract them into an evidence bundle.",
            schema={
                "type": "object",
                "properties": {
                    "input_root": {"type": "string"},
                    "extract_to": {"type": "string"},
                    "extract": {"type": "boolean", "default": False},
                    "max_depth": {"type": "integer", "default": 2},
                    "max_files": {"type": "integer", "default": 2000},
                    "max_total_bytes": {"type": "integer", "default": 500000000},
                },
                "required": ["input_root"],
                "additionalProperties": False,
            },
            executor="local_codex_lite.cli.cmd_evidence_artifacts_inspect",
            safety_level="safe",
            requires_exec=False,
        ),
        ToolDefinition(
            name="evidence.cve_scan",
            description="Install, update, and run cve-bin-tool scans with evidence outputs and high/critical reports.",
            schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "install", "update-db", "scan"],
                        "default": "scan",
                    },
                    "input_root": {"type": "string"},
                    "extract_to": {"type": "string"},
                    "output_dir": {"type": "string"},
                    "install": {"type": "boolean", "default": False},
                    "update_db": {"type": "boolean", "default": False},
                    "skip_unpack": {"type": "boolean", "default": False},
                    "offline": {"type": "boolean", "default": False},
                    "min_severity": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                        "default": "HIGH",
                    },
                    "format": {"type": "string", "default": "json,md,high-critical-md"},
                },
                "additionalProperties": False,
            },
            executor="local_codex_lite.cli.cmd_evidence_cve_scan",
            safety_level="safe",
            requires_exec=False,
        ),
    ]


def tool_brief_lines(tools: list[ToolDefinition]) -> list[str]:
    return [f"{item.name} - {item.description}" for item in tools]

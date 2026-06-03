"""``init`` / ``status`` / ``config show`` / ``recognize`` commands.

Small workspace-info and intent-routing handlers split out of ``cli.py``;
re-exported from ``cli`` for backwards compatibility.
"""

from __future__ import annotations

import argparse
import json

from .capabilities import discover_capabilities
from .cli_utils import console, workspace_root
from .config import (
    config_as_dict,
    config_path,
    default_config,
    load_config,
    save_config,
)
from .intent import decision_as_dict, recognize_intent


def cmd_init(args: argparse.Namespace) -> int:
    root = workspace_root()
    path = config_path(root)
    if path.exists():
        console.print(f"Config already exists: {path}")
        return 0
    save_config(root, default_config())
    console.print(f"Created {path}")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    cfg = load_config(workspace_root())
    console.print_json(json.dumps(config_as_dict(cfg), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    console.print(f"Workspace: {root}")
    console.print(f"Config: {config_path(root)}")
    console.print(f"LLM: {cfg.llm.base_url} / {cfg.llm.model}")
    return 0


def cmd_recognize(args: argparse.Namespace) -> int:
    decision = recognize_intent(args.task, discover_capabilities())
    console.print_json(json.dumps(decision_as_dict(decision), ensure_ascii=False, indent=2))
    return 0

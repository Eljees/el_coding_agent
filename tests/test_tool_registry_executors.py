"""Guard: every ToolDefinition.executor dotted-path must resolve to a real callable.

`tool_registry.default_tools()` stores executors as dotted strings (e.g.
``local_codex_lite.cli.cmd_logs_latest``). These are descriptive metadata, not
dynamically dispatched today, so they could silently rot if a target is renamed
or a cli re-export is dropped. This test keeps them honest.
"""
from __future__ import annotations

import importlib

import pytest

from local_codex_lite.tool_registry import default_tools


@pytest.mark.parametrize("tool", default_tools(), ids=lambda t: t.name)
def test_executor_path_resolves(tool) -> None:
    module_path, _, attr = tool.executor.rpartition(".")
    assert module_path, f"{tool.name}: executor '{tool.executor}' has no module part"
    module = importlib.import_module(module_path)
    target = getattr(module, attr, None)
    assert target is not None, f"{tool.name}: '{tool.executor}' does not resolve"
    assert callable(target), f"{tool.name}: '{tool.executor}' is not callable"

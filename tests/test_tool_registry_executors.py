"""Guard: every ToolDefinition.executor dotted-path must resolve to a real callable.

`tool_registry.default_tools()` stores executors as dotted strings (e.g.
``local_codex_lite.cli.cmd_logs_latest``). ``resolve_executor`` turns those
strings into live callables; this test ensures none of them silently rot if a
target is renamed or a cli re-export is dropped.
"""

from __future__ import annotations

import pytest

from local_codex_lite.tool_registry import default_tools, resolve_executor


@pytest.mark.parametrize("tool", default_tools(), ids=lambda t: t.name)
def test_executor_path_resolves(tool) -> None:
    target = resolve_executor(tool.executor)
    assert target is not None, f"{tool.name}: '{tool.executor}' did not resolve"
    assert callable(target), f"{tool.name}: '{tool.executor}' is not callable"


def test_resolve_executor_raises_on_bad_path() -> None:
    with pytest.raises((ModuleNotFoundError, AttributeError)):
        resolve_executor("local_codex_lite.tool_registry.nonexistent_fn")

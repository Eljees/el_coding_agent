"""Sanity check the reference plugin in ``examples/sample_capability_plugin/``.

This is not a packaging test (we don't actually run ``pip install`` on the
example here -- that's the developer's verification step).  Instead we
load the provider module by path, call it, and assert the shape of what
it returns.  That way any drift in the ``Capability`` contract that
breaks the example surfaces in the main test suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from local_codex_lite.capabilities import (
    CAPABILITY_ENTRY_POINT_GROUP,
    Capability,
    discover_capabilities,
)


def _load_provider():
    """Import the example's capabilities module from disk without installing
    the package."""
    repo_root = Path(__file__).resolve().parents[1]
    capabilities_path = (
        repo_root
        / "examples"
        / "sample_capability_plugin"
        / "sample_capability_plugin"
        / "capabilities.py"
    )
    if not capabilities_path.is_file():
        pytest.skip("sample_capability_plugin example not present in this checkout")
    spec = importlib.util.spec_from_file_location(
        "sample_capability_plugin_test_loader",
        capabilities_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Shape of the example
# ---------------------------------------------------------------------------


def test_example_provide_is_callable() -> None:
    module = _load_provider()
    assert callable(module.provide)


def test_example_provide_returns_capability_list() -> None:
    module = _load_provider()
    out = module.provide()
    assert isinstance(out, list)
    assert len(out) >= 1
    for item in out:
        assert isinstance(item, Capability)


def test_example_capability_has_safe_defaults() -> None:
    """The example must not pretend to be safety-critical or require
    --apply / --exec, otherwise it would be a bad reference template."""
    module = _load_provider()
    cap = module.provide()[0]
    assert cap.safety_level == "safe"
    assert cap.requires_apply is False
    assert cap.requires_exec is False


def test_example_capability_uses_namespaced_id() -> None:
    """The example shows newcomers the right way to namespace; a bare id
    like 'echo' would be misleading."""
    module = _load_provider()
    cap = module.provide()[0]
    assert "." in cap.id, f"example id {cap.id!r} should be namespaced (e.g. 'sample.echo')"


# ---------------------------------------------------------------------------
# discover_capabilities() picks the example up when entry_points returns it.
# We don't install the package; instead we monkeypatch the entry-points API
# to return a fake EntryPoint whose .load() yields the example's provide().
# ---------------------------------------------------------------------------


def test_example_can_be_loaded_via_entry_points(monkeypatch) -> None:
    module = _load_provider()
    provider = module.provide

    class _FakeEP:
        def __init__(self) -> None:
            self.name = "sample_capabilities"
            self.group = CAPABILITY_ENTRY_POINT_GROUP

        def load(self):
            return provider

    def fake_entry_points(*, group=None):
        if group == CAPABILITY_ENTRY_POINT_GROUP:
            return [_FakeEP()]
        return []

    monkeypatch.setattr(
        "local_codex_lite.capabilities._metadata.entry_points",
        fake_entry_points,
    )

    merged = discover_capabilities()
    plugin_ids = {cap.id for cap in merged}
    sample_id = provider()[0].id
    assert sample_id in plugin_ids

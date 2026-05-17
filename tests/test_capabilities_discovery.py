"""Tests for the entry_points-based capability discovery.

Third-party packages can extend the agent's capability set by registering
a callable under the ``local_codex_lite.capabilities`` entry-point group.
``discover_capabilities()`` is the merge function the CLI and UI use.

These tests fabricate ``EntryPoint`` objects directly and monkeypatch
``importlib.metadata.entry_points`` so we never depend on a real
installed package.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_codex_lite import capabilities as capmod
from local_codex_lite.capabilities import (
    CAPABILITY_ENTRY_POINT_GROUP,
    Capability,
    default_capabilities,
    discover_capabilities,
)


def _cap(cid: str) -> Capability:
    return Capability(
        id=cid,
        title=f"plugin {cid}",
        description=f"plugin capability {cid}",
        examples=(),
        keywords=(cid,),
        required_inputs=(),
        safety_level="safe",
        requires_apply=False,
        requires_exec=False,
        cli_equivalent=f"python -m local_codex_lite {cid}",
    )


class _FakeEntryPoint:
    """Mimic the relevant slice of importlib.metadata.EntryPoint."""

    def __init__(self, name: str, provider) -> None:
        self.name = name
        self.group = CAPABILITY_ENTRY_POINT_GROUP
        self._provider = provider

    def load(self):
        return self._provider


def _install_eps(monkeypatch, *entry_points: _FakeEntryPoint) -> None:
    """Make capabilities._metadata.entry_points(group=...) return the list
    of fake entry points regardless of how the metadata API is called."""
    def fake(*, group=None):
        if group == CAPABILITY_ENTRY_POINT_GROUP:
            return list(entry_points)
        return []
    monkeypatch.setattr(capmod._metadata, "entry_points", fake)


# ---------------------------------------------------------------------------
# Built-in path: no plugins installed
# ---------------------------------------------------------------------------

def test_discover_returns_builtins_when_no_plugins(monkeypatch) -> None:
    _install_eps(monkeypatch)  # empty
    out = discover_capabilities()
    builtin_ids = {cap.id for cap in default_capabilities()}
    out_ids = {cap.id for cap in out}
    assert out_ids == builtin_ids


# ---------------------------------------------------------------------------
# Plugin contributions are merged in
# ---------------------------------------------------------------------------

def test_discover_merges_plugin_single_capability(monkeypatch) -> None:
    def provider():
        return _cap("my_team.foo")
    _install_eps(monkeypatch, _FakeEntryPoint("my_team_foo", provider))
    out = discover_capabilities()
    assert any(cap.id == "my_team.foo" for cap in out)


def test_discover_merges_plugin_list_of_capabilities(monkeypatch) -> None:
    def provider():
        return [_cap("plug.a"), _cap("plug.b")]
    _install_eps(monkeypatch, _FakeEntryPoint("plug", provider))
    out_ids = {cap.id for cap in discover_capabilities()}
    assert {"plug.a", "plug.b"}.issubset(out_ids)


# ---------------------------------------------------------------------------
# Built-ins always win on id collision
# ---------------------------------------------------------------------------

def test_discover_ignores_plugin_that_collides_with_builtin(monkeypatch) -> None:
    """A plugin must not be able to redefine a safety-critical capability
    such as run.apply.  Built-in wins; plugin entry is silently dropped."""
    builtin = next(cap for cap in default_capabilities() if cap.id == "run.apply")

    def hostile_provider():
        return [_cap("run.apply")]  # tries to override run.apply
    _install_eps(monkeypatch, _FakeEntryPoint("hostile", hostile_provider))
    out = discover_capabilities()
    matches = [cap for cap in out if cap.id == "run.apply"]
    assert len(matches) == 1
    # The surviving record is the built-in, not the plugin's fake.
    assert matches[0].title == builtin.title
    assert matches[0].cli_equivalent == builtin.cli_equivalent


# ---------------------------------------------------------------------------
# Misbehaving plugins are skipped, not fatal
# ---------------------------------------------------------------------------

def test_discover_skips_provider_that_raises(monkeypatch) -> None:
    def boom():
        raise RuntimeError("plugin broken")
    _install_eps(monkeypatch, _FakeEntryPoint("boom", boom))
    out = discover_capabilities()
    # Built-ins still present, nothing else.
    assert {cap.id for cap in out} == {cap.id for cap in default_capabilities()}


def test_discover_skips_provider_that_returns_wrong_type(monkeypatch) -> None:
    def weird():
        return 42  # neither Capability nor list
    _install_eps(monkeypatch, _FakeEntryPoint("weird", weird))
    out = discover_capabilities()
    assert {cap.id for cap in out} == {cap.id for cap in default_capabilities()}


def test_discover_skips_non_capability_items_inside_list(monkeypatch) -> None:
    def mixed():
        return [_cap("plug.valid"), "this is not a Capability", 123]
    _install_eps(monkeypatch, _FakeEntryPoint("mixed", mixed))
    ids = {cap.id for cap in discover_capabilities()}
    assert "plug.valid" in ids
    # The garbage entries did not bring anything else in.
    extras = ids - {cap.id for cap in default_capabilities()}
    assert extras == {"plug.valid"}

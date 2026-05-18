"""Smoke tests for ``local-codex-lite plugins list``.

We don't actually pip-install a plugin here -- we monkeypatch
``discover_capabilities_with_source`` to return a controlled mix of
built-in and plugin entries and check the formatting / counts.
"""
from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout

import pytest

from local_codex_lite import plugins_cmd
from local_codex_lite.capabilities import Capability, CapabilitySource


def _fake_entries():
    builtin = Capability(
        id="run.preview",
        title="Preview code changes",
        description="...",
        examples=(),
        keywords=(),
        required_inputs=("task",),
        safety_level="safe",
        requires_apply=False,
        requires_exec=False,
        cli_equivalent="",
    )
    plugin = Capability(
        id="sample.echo",
        title="Echo a task back to the user",
        description="...",
        examples=(),
        keywords=(),
        required_inputs=("task",),
        safety_level="safe",
        requires_apply=False,
        requires_exec=False,
        cli_equivalent="",
    )
    return [
        (CapabilitySource(kind="builtin", name=""), builtin),
        (CapabilitySource(kind="plugin", name="sample_capabilities"), plugin),
    ]


def _run(args_ns, monkeypatch):
    monkeypatch.setattr(
        plugins_cmd, "discover_capabilities_with_source", _fake_entries
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = plugins_cmd.cmd_plugins_list(args_ns)
    return rc, buf.getvalue()


def test_text_output_shows_both_sources(monkeypatch):
    ns = argparse.Namespace(plugins_only=False, json_output=False)
    rc, out = _run(ns, monkeypatch)
    assert rc == 0
    assert "run.preview" in out
    assert "sample.echo" in out
    assert "builtin" in out
    assert "plugin" in out
    assert "sample_capabilities" in out
    assert "2 total (1 built-in, 1 from plugins)" in out


def test_plugins_only_drops_builtins(monkeypatch):
    ns = argparse.Namespace(plugins_only=True, json_output=False)
    rc, out = _run(ns, monkeypatch)
    assert rc == 0
    assert "sample.echo" in out
    assert "run.preview" not in out
    # summary line still mentions plugin count
    assert "1 from plugins" in out


def test_json_output_shape(monkeypatch):
    import json
    ns = argparse.Namespace(plugins_only=False, json_output=True)
    rc, out = _run(ns, monkeypatch)
    assert rc == 0
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 2
    builtin = next(d for d in data if d["source"]["kind"] == "builtin")
    plugin = next(d for d in data if d["source"]["kind"] == "plugin")
    assert builtin["capability"]["id"] == "run.preview"
    assert plugin["source"]["name"] == "sample_capabilities"
    assert plugin["capability"]["required_inputs"] == ["task"]


def test_empty_plugins_only_message(monkeypatch):
    # no entries at all
    monkeypatch.setattr(
        plugins_cmd, "discover_capabilities_with_source", lambda: []
    )
    ns = argparse.Namespace(plugins_only=True, json_output=False)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = plugins_cmd.cmd_plugins_list(ns)
    assert rc == 0
    assert "(no capabilities found)" in buf.getvalue()

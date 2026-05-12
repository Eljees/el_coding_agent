from __future__ import annotations

import runpy

import pytest

import local_codex_lite.cli as cli


def test_module_entrypoint_propagates_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 7)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("local_codex_lite.__main__", run_name="__main__")

    assert exc_info.value.code == 7

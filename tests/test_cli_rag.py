"""Unit tests for the ``rag index`` / ``rag query`` command handlers.

These handlers had no direct coverage after they were split into cli_rag.py;
this locks down their success, empty-result and RagProviderError branches by
faking the underlying rag.* calls (no embeddings / vector store needed).
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from local_codex_lite import cli_rag
from local_codex_lite.config import AgentConfig
from local_codex_lite.rag import RagProviderError


def _patch_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_rag, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli_rag, "load_config", lambda root: AgentConfig())


def test_rag_index_success(monkeypatch, tmp_path, capsys) -> None:
    _patch_env(monkeypatch, tmp_path)
    info = SimpleNamespace(
        index_path=tmp_path / "idx", provider="fake", chunk_count=3, file_count=2
    )
    monkeypatch.setattr(cli_rag, "rag_index_workspace", lambda root, cfg: info)
    assert cli_rag.cmd_rag_index(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "RAG index built" in out
    assert "Chunks: 3" in out


def test_rag_index_provider_error(monkeypatch, tmp_path, capsys) -> None:
    _patch_env(monkeypatch, tmp_path)

    def boom(root, cfg):
        raise RagProviderError("no provider configured")

    monkeypatch.setattr(cli_rag, "rag_index_workspace", boom)
    assert cli_rag.cmd_rag_index(argparse.Namespace()) == 1
    assert "RAG index failed" in capsys.readouterr().out


def test_rag_query_no_matches(monkeypatch, tmp_path, capsys) -> None:
    _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_rag, "rag_query_index", lambda q, root, cfg, top_k=None: [])
    assert cli_rag.cmd_rag_query(argparse.Namespace(query="x", top_k=None)) == 0
    assert "No RAG matches" in capsys.readouterr().out


def test_rag_query_success(monkeypatch, tmp_path) -> None:
    _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_rag, "rag_query_index", lambda q, root, cfg, top_k=None: [{"hit": 1}])
    monkeypatch.setattr(cli_rag, "format_retrieved_context", lambda retrieved, limit: "CONTEXT")
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        cli_rag, "_print_retrieved_rag_context", lambda text: captured.update(text=text)
    )
    assert cli_rag.cmd_rag_query(argparse.Namespace(query="x", top_k=3)) == 0
    assert captured["text"] == "CONTEXT"


def test_rag_query_provider_error(monkeypatch, tmp_path, capsys) -> None:
    _patch_env(monkeypatch, tmp_path)

    def boom(q, root, cfg, top_k=None):
        raise RagProviderError("vector store down")

    monkeypatch.setattr(cli_rag, "rag_query_index", boom)
    assert cli_rag.cmd_rag_query(argparse.Namespace(query="x", top_k=None)) == 1
    assert "RAG query failed" in capsys.readouterr().out

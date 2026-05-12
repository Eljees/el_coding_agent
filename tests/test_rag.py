from __future__ import annotations

from pathlib import Path

import pytest

from local_codex_lite.config import default_config
from local_codex_lite.rag import (
    RagProviderError,
    build_chunks,
    ensure_rag_provider_supported,
    format_retrieved_context,
    index_workspace,
    query_index,
    resolve_store_dir,
    RetrievedChunk,
)


def test_keyword_provider_is_default() -> None:
    cfg = default_config()
    assert cfg.rag.provider == "keyword"
    assert ensure_rag_provider_supported(cfg) == "keyword"


def test_unsupported_provider_raises_clear_error(tmp_path: Path) -> None:
    cfg = default_config().model_copy(deep=True)
    cfg.rag.provider = "chroma"

    with pytest.raises(RagProviderError, match="provider 'chroma' is configured but not implemented"):
        ensure_rag_provider_supported(cfg)


def test_keyword_indexing_and_query_excludes_sensitive_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Line1\npatch repair\nLine3\n", encoding="utf-8")
    (tmp_path / "secret.env").write_text("API_KEY=123", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not included by default", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("print('ignore')", encoding="utf-8")
    cfg = default_config()

    chunks = build_chunks(tmp_path, cfg)
    assert any(chunk.path.name == "README.md" for chunk in chunks)
    assert not any(chunk.path.name == "secret.env" for chunk in chunks)
    assert not any(chunk.path.name == "notes.txt" for chunk in chunks)
    assert not any(".venv" in chunk.path.as_posix() for chunk in chunks)

    info = index_workspace(tmp_path, cfg)
    results = query_index("patch repair", tmp_path, cfg)

    assert info.chunk_count >= 1
    assert results
    assert results[0].path.name == "README.md"
    assert "patch" in results[0].reason
    assert all(chunk.path.name != "secret.env" for chunk in results)


def test_retrieved_context_formatting_includes_path_and_snippet() -> None:
    chunk = RetrievedChunk(
        path=Path("foo.py"),
        start_line=10,
        end_line=12,
        text="def foo():\n    return 1\n",
        score=2.5,
        reason="matched: foo",
    )

    out = format_retrieved_context([chunk], max_context_chars=1000)

    assert "### foo.py [10-12]" in out
    assert "score=2.5" in out
    assert "def foo()" in out


def test_store_dir_must_stay_inside_workspace(tmp_path: Path) -> None:
    cfg = default_config().model_copy(deep=True)
    cfg.rag.store_dir = str(tmp_path.parent / "outside-rag")

    with pytest.raises(RagProviderError, match="must stay inside the workspace"):
        resolve_store_dir(tmp_path, cfg)

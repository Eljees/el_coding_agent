"""Coverage for rag.py — uncovered filter branches, scoring, format overflow,
chunking long text, _load_index missing index, and retrieve_rag_context."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from local_codex_lite.config import default_config
from local_codex_lite.rag import (
    RagProviderError,
    _compact_snippet,
    _is_blocked_rel_path,
    _load_index,
    _split_into_chunks,
    build_chunks,
    ensure_rag_provider_supported,
    format_retrieved_context,
    index_workspace,
    query_index,
    retrieve_rag_context,
)

# ---------------------------------------------------------------------------
# ensure_rag_provider_supported — unrecognized provider (line 65)
# ---------------------------------------------------------------------------


def test_ensure_rag_provider_unsupported_raises_rag_provider_error() -> None:
    cfg = default_config().model_copy(deep=True)
    cfg.rag.provider = "faiss"
    with pytest.raises(RagProviderError, match="not recognized"):
        ensure_rag_provider_supported(cfg)


# ---------------------------------------------------------------------------
# build_chunks — file inside store_dir is skipped (line 91 + _is_blocked_rel_path line 319)
# ---------------------------------------------------------------------------


def test_build_chunks_skips_files_inside_store_dir(tmp_path: Path) -> None:
    cfg = default_config().model_copy(deep=True)
    # Use a store_dir name not in BLOCKED_RUNTIME_DIRS so os.walk actually enters it
    cfg.rag.store_dir = "my-rag-store"
    store_dir = tmp_path / "my-rag-store"
    store_dir.mkdir(parents=True)
    (store_dir / "index.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("keyword content\n", encoding="utf-8")
    chunks = build_chunks(tmp_path, cfg)
    assert not any("index.json" in str(c.path) for c in chunks)
    assert any(c.path.name == "README.md" for c in chunks)


# ---------------------------------------------------------------------------
# _is_blocked_rel_path — path IS inside blocked_root returns True (line 319)
# ---------------------------------------------------------------------------


def test_is_blocked_rel_path_returns_true_for_path_inside_blocked() -> None:
    blocked = Path(".local-codex-lite/rag-store")
    child = Path(".local-codex-lite/rag-store/index.json")
    assert _is_blocked_rel_path(child, blocked) is True


def test_is_blocked_rel_path_returns_false_for_unrelated_path() -> None:
    blocked = Path(".local-codex-lite/rag-store")
    other = Path("README.md")
    assert _is_blocked_rel_path(other, blocked) is False


# ---------------------------------------------------------------------------
# build_chunks — exclude glob filter (line 97)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# build_chunks — path_has_blocked_dir filter (line 93)
# ---------------------------------------------------------------------------


def test_build_chunks_skips_file_with_blocked_dir_component(tmp_path: Path) -> None:
    import os as _os

    cfg = default_config()
    (tmp_path / "README.md").write_text("content\n", encoding="utf-8")
    # Inject a fake os.walk entry whose dirpath contains a BLOCKED_RUNTIME_DIR
    # component, which bypasses the normal dirnames filtering.
    real_walk = _os.walk

    def patched_walk(root_path, **kwargs):
        yield from real_walk(root_path, **kwargs)
        # Inject a fake dirpath that looks like a blocked-dir sub-path
        yield str(tmp_path / "__pycache__"), [], ["some.pyc"]

    with patch("local_codex_lite.rag.os.walk", side_effect=patched_walk):
        chunks = build_chunks(tmp_path, cfg)

    assert not any("some.pyc" in str(c.path) for c in chunks)


def test_build_chunks_skips_excluded_glob(tmp_path: Path) -> None:
    cfg = default_config().model_copy(deep=True)
    cfg.rag.exclude_globs = ["*.md"]
    (tmp_path / "README.md").write_text("some content\n", encoding="utf-8")
    chunks = build_chunks(tmp_path, cfg)
    assert not any(c.path.name == "README.md" for c in chunks)


# ---------------------------------------------------------------------------
# build_chunks — oversized file is skipped (line 103)
# ---------------------------------------------------------------------------


def test_build_chunks_skips_file_exceeding_max_bytes(tmp_path: Path) -> None:
    cfg = default_config().model_copy(deep=True)
    cfg.workspace.max_file_bytes = 10
    (tmp_path / "README.md").write_text("x" * 100, encoding="utf-8")
    chunks = build_chunks(tmp_path, cfg)
    assert not any(c.path.name == "README.md" for c in chunks)


# ---------------------------------------------------------------------------
# build_chunks — unreadable file is skipped (lines 106-107)
# ---------------------------------------------------------------------------


def test_build_chunks_skips_oserror_on_read(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("content\n", encoding="utf-8")
    original_read = Path.read_text

    def raise_on_readme(self: Path, **kwargs: object) -> str:
        if self.name == "README.md":
            raise OSError("Permission denied")
        return original_read(self, **kwargs)  # type: ignore[return-value]

    with patch.object(Path, "read_text", raise_on_readme):
        chunks = build_chunks(tmp_path, cfg)
    assert not any(c.path.name == "README.md" for c in chunks)


# ---------------------------------------------------------------------------
# build_chunks — file outside workspace is skipped (line 99)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# build_chunks — sensitive file matching include_glob is skipped (line 101)
# ---------------------------------------------------------------------------


def test_build_chunks_skips_sensitive_file_matching_include_glob(tmp_path: Path) -> None:
    cfg = default_config().model_copy(deep=True)
    # Remove the **/*secret* exclude_glob so the file is not filtered there but
    # is_sensitive_path kicks in (line 100-101) instead.
    cfg.rag.exclude_globs = [g for g in cfg.rag.exclude_globs if "*secret*" not in g]
    # secrets.yaml matches **/*.yaml (include) and *secret* (sensitive)
    (tmp_path / "secrets.yaml").write_text("api_key: hunter2\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("normal content\n", encoding="utf-8")
    chunks = build_chunks(tmp_path, cfg)
    assert not any(c.path.name == "secrets.yaml" for c in chunks)
    assert any(c.path.name == "README.md" for c in chunks)


def test_build_chunks_skips_file_outside_workspace(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("content\n", encoding="utf-8")

    real_is_inside = __import__(
        "local_codex_lite.safety", fromlist=["is_inside_workspace"]
    ).is_inside_workspace

    def fake_is_inside(path: Path, root: Path) -> bool:
        if path.name == "README.md":
            return False
        return real_is_inside(path, root)

    with patch("local_codex_lite.rag.is_inside_workspace", side_effect=fake_is_inside):
        chunks = build_chunks(tmp_path, cfg)
    assert not any(c.path.name == "README.md" for c in chunks)


# ---------------------------------------------------------------------------
# query_index — auto-builds index when missing (line 183)
# ---------------------------------------------------------------------------


def test_query_index_auto_builds_index_when_missing(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("keyword content\n", encoding="utf-8")
    store_dir = tmp_path / cfg.rag.store_dir
    assert not (store_dir / "index.json").exists()
    results = query_index("keyword", tmp_path, cfg)
    assert (store_dir / "index.json").exists()
    assert any(r.path.name == "README.md" for r in results)


# ---------------------------------------------------------------------------
# query_index — empty/short query returns [] (line 187)
# ---------------------------------------------------------------------------


def test_query_index_returns_empty_list_for_empty_query(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("content\n", encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = query_index("", tmp_path, cfg)
    assert results == []


def test_query_index_returns_empty_list_for_single_char_query(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("content\n", encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = query_index("x", tmp_path, cfg)
    assert results == []


# ---------------------------------------------------------------------------
# query_index — token matches in path gets score boost (line 199)
# ---------------------------------------------------------------------------


def test_query_index_boosts_score_for_path_token_match(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("readme readme readme\n", encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = query_index("readme", tmp_path, cfg)
    assert results
    assert results[0].score > 0


def test_query_index_skips_chunks_with_no_matching_tokens(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "match.md").write_text("uniqueterm here\n", encoding="utf-8")
    (tmp_path / "nomatch.md").write_text("nothing relevant\n", encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = query_index("uniqueterm", tmp_path, cfg)
    assert any(r.path.name == "match.md" for r in results)
    assert not any(r.path.name == "nomatch.md" for r in results)


# ---------------------------------------------------------------------------
# retrieve_rag_context — wires through query_index (line 221)
# ---------------------------------------------------------------------------


def test_retrieve_rag_context_returns_results(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("unique_term content\n", encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = retrieve_rag_context("unique_term", tmp_path, cfg)
    assert any(r.path.name == "README.md" for r in results)


def test_retrieve_rag_context_passes_top_k(tmp_path: Path) -> None:
    cfg = default_config()
    (tmp_path / "README.md").write_text("term content term\n", encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = retrieve_rag_context("term", tmp_path, cfg, top_k=1)
    assert len(results) <= 1


# ---------------------------------------------------------------------------
# format_retrieved_context — overflow stops appending chunks (lines 230, 235)
# ---------------------------------------------------------------------------


def test_format_retrieved_context_skips_chunk_with_empty_text() -> None:
    from local_codex_lite.rag import RetrievedChunk

    empty_chunk = RetrievedChunk(
        path=Path("foo.py"),
        start_line=1,
        end_line=1,
        text="   ",
        score=1.0,
    )
    result = format_retrieved_context([empty_chunk], max_context_chars=1000)
    assert result == ""


def test_format_retrieved_context_stops_when_max_chars_exceeded() -> None:
    from local_codex_lite.rag import RetrievedChunk

    big_text = "x" * 500
    chunk_a = RetrievedChunk(path=Path("a.py"), start_line=1, end_line=5, text=big_text, score=2.0)
    chunk_b = RetrievedChunk(path=Path("b.py"), start_line=1, end_line=5, text=big_text, score=1.0)
    result = format_retrieved_context([chunk_a, chunk_b], max_context_chars=80)
    # Only the first chunk fits; second triggers the break
    assert "a.py" in result
    assert "b.py" not in result


def test_format_retrieved_context_stops_at_max_context_chars(tmp_path: Path) -> None:
    cfg = default_config()
    content = "alpha beta gamma delta " * 50
    (tmp_path / "a.md").write_text(content, encoding="utf-8")
    (tmp_path / "b.md").write_text(content, encoding="utf-8")
    index_workspace(tmp_path, cfg)
    results = retrieve_rag_context("alpha", tmp_path, cfg, top_k=10)
    tiny_max = 50
    formatted = format_retrieved_context(results, tiny_max)
    assert len(formatted) <= tiny_max + 200  # some slack for the header


# ---------------------------------------------------------------------------
# _compact_snippet — truncation branch (line 245)
# ---------------------------------------------------------------------------


def test_compact_snippet_truncates_long_text() -> None:
    long_text = "x" * 2000
    result = _compact_snippet(long_text, max_context_chars=240)
    assert result.endswith("...")
    assert len(result) < 2000


# ---------------------------------------------------------------------------
# _load_index — returns [] when index.json missing (line 252)
# ---------------------------------------------------------------------------


def test_load_index_returns_empty_list_when_no_index(tmp_path: Path) -> None:
    cfg = default_config()
    chunks = _load_index(tmp_path, cfg)
    assert chunks == []


# ---------------------------------------------------------------------------
# _split_into_chunks — long text produces multiple chunks (lines 272-280)
# ---------------------------------------------------------------------------


def test_split_into_chunks_long_text_produces_multiple_chunks() -> None:
    text = "a" * 200
    chunks = _split_into_chunks(text, chunk_chars=80, overlap=10)
    assert len(chunks) > 1
    assert all(len(chunk_text) <= 80 for _, _, chunk_text in chunks)
    assert chunks[0][0] == 0
    combined = set()
    for start, end, _chunk_text in chunks:
        for idx in range(start, end):
            combined.add(idx)
    assert combined == set(range(len(text)))


def test_split_into_chunks_short_text_returns_single_chunk() -> None:
    text = "short"
    chunks = _split_into_chunks(text, chunk_chars=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0] == (0, len(text), text)

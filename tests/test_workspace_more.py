"""Additional coverage for workspace.py — uncovered filter branches."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from local_codex_lite.config import WorkspaceConfig, default_config
from local_codex_lite.workspace import (
    build_tree,
    read_file_chunks,
    summarize_ranked_files,
)


def _cfg(**overrides) -> WorkspaceConfig:
    cfg = default_config().workspace
    for key, val in overrides.items():
        object.__setattr__(cfg, key, val)
    return cfg


# ---------------------------------------------------------------------------
# build_tree — exclude_glob hit (line 94)
# ---------------------------------------------------------------------------


def test_build_tree_exclude_glob_skips_matching_file(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "skip.log").write_text("noise\n", encoding="utf-8")
    cfg = default_config().workspace.model_copy(update={"exclude_globs": ["*.log"]})
    result = build_tree(tmp_path, cfg)
    assert any("keep.py" in r for r in result)
    assert not any("skip.log" in r for r in result)


# ---------------------------------------------------------------------------
# _score_workspace_file — config file score (lines 242-243)
# ---------------------------------------------------------------------------


def test_rank_workspace_files_scores_config_file(tmp_path: Path) -> None:
    from local_codex_lite.workspace import rank_workspace_files

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    cfg = default_config().workspace.model_copy(update={"include_globs": []})
    result = rank_workspace_files(tmp_path, "zzz_unrelated_task", cfg)
    toml_file = next((r for r in result if r.path.name == "pyproject.toml"), None)
    assert toml_file is not None
    assert "config file" in toml_file.reasons


# ---------------------------------------------------------------------------
# summarize_ranked_files — can_read_path returns False (line 151)
# ---------------------------------------------------------------------------


def test_summarize_ranked_files_skips_sensitive_py_file(tmp_path: Path) -> None:
    # secret.py matches **/*.py (include_glob) AND *secret* (SENSITIVE_GLOB)
    (tmp_path / "normal.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("API_KEY = 'hunter2'\n", encoding="utf-8")
    cfg = default_config()
    result = summarize_ranked_files(tmp_path, "normal", cfg.workspace, allow_sensitive_read=False)
    paths = [item.path.name for item in result]
    assert "normal.py" in paths
    assert "secret.py" not in paths


# ---------------------------------------------------------------------------
# summarize_ranked_files — limit reached (lines 154-155)
# ---------------------------------------------------------------------------


def test_summarize_ranked_files_respects_limit(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"file{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
    cfg = default_config()
    result = summarize_ranked_files(
        tmp_path, "file", cfg.workspace, allow_sensitive_read=False, limit=2
    )
    assert len(result) <= 2


# ---------------------------------------------------------------------------
# read_file_chunks — can_read_path False (line 166)
# ---------------------------------------------------------------------------


def test_read_file_chunks_skips_sensitive_path(tmp_path: Path) -> None:
    sensitive = tmp_path / ".env"
    sensitive.write_text("SECRET=1\n", encoding="utf-8")
    chunks = read_file_chunks(tmp_path, [sensitive], max_bytes=100_000, allow_sensitive_read=False)
    assert not any(c.path.name == ".env" for c in chunks)


# ---------------------------------------------------------------------------
# read_file_chunks — path.is_file() False (line 168)
# ---------------------------------------------------------------------------


def test_read_file_chunks_skips_nonexistent_path(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.py"
    chunks = read_file_chunks(tmp_path, [missing], max_bytes=100_000, allow_sensitive_read=False)
    assert chunks == []


# ---------------------------------------------------------------------------
# read_file_chunks — size > max_bytes (line 171)
# ---------------------------------------------------------------------------


def test_read_file_chunks_skips_oversized_file(tmp_path: Path) -> None:
    big = tmp_path / "big.py"
    big.write_text("x" * 1000, encoding="utf-8")
    chunks = read_file_chunks(tmp_path, [big], max_bytes=10, allow_sensitive_read=True)
    assert chunks == []


# ---------------------------------------------------------------------------
# _score_workspace_file — baseline ranking (line 269)
# ---------------------------------------------------------------------------


def test_rank_workspace_files_assigns_baseline_to_unmatched_file(tmp_path: Path) -> None:
    from local_codex_lite.workspace import rank_workspace_files

    # A .txt file is not Python, not a config, not important, not in tests
    (tmp_path / "data.txt").write_text("some data\n", encoding="utf-8")
    cfg = default_config().workspace.model_copy(update={"include_globs": []})
    result = rank_workspace_files(tmp_path, "zzz_unrelated_task", cfg)
    assert result
    data_file = next((r for r in result if r.path.name == "data.txt"), None)
    assert data_file is not None
    assert "baseline ranking" in data_file.reasons

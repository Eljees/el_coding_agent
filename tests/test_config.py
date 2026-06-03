"""Tests for local_codex_lite.config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from local_codex_lite.config import (
    AgentConfig,
    LLMConfig,
    SafetyConfig,
    WorkspaceConfig,
    config_as_dict,
    config_path,
    default_config,
    load_config,
    save_config,
)


def test_default_config_has_expected_defaults() -> None:
    cfg = default_config()
    assert cfg.llm.base_url == "http://localhost:8015/v1"
    assert cfg.llm.model == "qwen25-coder-14b-awq"
    assert cfg.llm.temperature >= 0.0
    assert cfg.llm.max_tokens > 0


def test_config_as_dict_is_serialisable() -> None:
    cfg = default_config()
    d = config_as_dict(cfg)
    assert isinstance(d, dict)
    assert "llm" in d
    assert isinstance(d["llm"]["base_url"], str)


def test_save_and_load_config_roundtrip(tmp_path: Path) -> None:
    base = default_config()
    # Build the updated config via model_copy so the test does not rely on
    # in-place mutation of nested pydantic models (which is allowed today but
    # would break the moment we set frozen=True or validate_assignment=True).
    cfg = base.model_copy(
        update={"llm": base.llm.model_copy(update={"model": "test-model-roundtrip"})}
    )
    path = save_config(tmp_path, cfg)
    assert path.exists()
    loaded = load_config(tmp_path)
    assert loaded.llm.model == "test-model-roundtrip"
    # Sanity-check the rag section also survives a save/load round trip so a
    # future drift between config.example.yaml and AgentConfig is caught here.
    assert loaded.rag.enabled is True
    assert loaded.rag.provider == "keyword"


def test_load_config_missing_file_returns_default(tmp_path: Path) -> None:
    workspace = tmp_path / "nonexistent"
    cfg = load_config(workspace)
    # Should silently return defaults when file is absent
    assert isinstance(cfg, AgentConfig)
    assert cfg.llm.base_url == "http://localhost:8015/v1"


def test_config_path_uses_workspace_root(tmp_path: Path) -> None:
    path = config_path(tmp_path)
    assert path.parent.name == ".local-codex-lite"
    assert path.name == "config.yaml"


def test_safety_config_defaults_are_conservative() -> None:
    cfg = default_config()
    # apply and exec must default to False (require explicit opt-in)
    assert cfg.safety.require_apply_flag is True
    assert cfg.safety.require_exec_flag is True

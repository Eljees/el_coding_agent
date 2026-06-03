"""Tests for the --profile flag: swap cfg.llm with a named profile per
invocation, leaving config.yaml untouched."""

from __future__ import annotations

from pathlib import Path

import pytest

from local_codex_lite import cli
from local_codex_lite.config import (
    AgentConfig,
    LLMConfig,
    UnknownProfileError,
    apply_profile,
    default_config,
    load_config,
    save_config,
)

# ---------------------------------------------------------------------------
# apply_profile pure logic
# ---------------------------------------------------------------------------


def test_apply_profile_none_returns_same_config() -> None:
    cfg = default_config()
    out = apply_profile(cfg, None)
    assert out is cfg or out == cfg
    assert out.llm.base_url == cfg.llm.base_url


def test_apply_profile_empty_string_returns_same_config() -> None:
    cfg = default_config()
    # An empty/missing CLI flag should be a no-op, not an error.
    assert apply_profile(cfg, "").llm.base_url == cfg.llm.base_url


def test_apply_profile_swaps_llm_with_named_profile() -> None:
    base = default_config()
    fast = LLMConfig(base_url="http://localhost:8100/v1", model="fast-7b")
    cfg = base.model_copy(update={"llm_profiles": {"fast": fast}})
    out = apply_profile(cfg, "fast")
    assert out.llm.base_url == "http://localhost:8100/v1"
    assert out.llm.model == "fast-7b"
    # Original config is not mutated.
    assert cfg.llm.base_url == base.llm.base_url


def test_apply_profile_unknown_name_raises_with_available_list() -> None:
    base = default_config()
    cfg = base.model_copy(
        update={
            "llm_profiles": {
                "fast": LLMConfig(model="fast-7b"),
                "review": LLMConfig(model="strict-32b"),
            }
        }
    )
    with pytest.raises(UnknownProfileError) as exc_info:
        apply_profile(cfg, "missing")
    msg = str(exc_info.value)
    assert "missing" in msg
    assert "fast" in msg
    assert "review" in msg


def test_apply_profile_unknown_with_no_profiles_configured() -> None:
    """When no profiles are configured at all, the error message says so
    instead of pointing at an empty list."""
    cfg = default_config()
    with pytest.raises(UnknownProfileError) as exc_info:
        apply_profile(cfg, "anything")
    assert "(none configured)" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Config round-trip preserves llm_profiles
# ---------------------------------------------------------------------------


def test_profiles_round_trip_via_yaml(tmp_path: Path) -> None:
    cfg = default_config()
    cfg = cfg.model_copy(
        update={
            "llm_profiles": {
                "fast": LLMConfig(base_url="http://localhost:8100/v1", model="fast-7b"),
                "review": LLMConfig(base_url="http://localhost:8200/v1", model="strict-32b"),
            }
        }
    )
    save_config(tmp_path, cfg)
    loaded = load_config(tmp_path)
    assert set(loaded.llm_profiles.keys()) == {"fast", "review"}
    assert loaded.llm_profiles["fast"].model == "fast-7b"
    assert loaded.llm_profiles["review"].base_url == "http://localhost:8200/v1"


# ---------------------------------------------------------------------------
# argparse wires --profile through run / preview / ask / review
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "task", "--apply", "--profile", "fast"],
        ["preview", "task", "--profile", "review"],
        ["ask", "question", "--profile", "fast"],
        ["review", "--base", "main", "--profile", "review"],
    ],
)
def test_build_parser_carries_profile(argv: list[str]) -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(argv)
    assert ns.profile in {"fast", "review"}


def test_build_parser_profile_defaults_to_none() -> None:
    parser = cli.build_parser()
    for argv in (
        ["run", "task", "--apply"],
        ["preview", "task"],
        ["ask", "question"],
        ["review"],
    ):
        ns = parser.parse_args(argv)
        assert getattr(ns, "profile", "_missing") is None

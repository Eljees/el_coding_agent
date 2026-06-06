"""docs/cli-reference.md must stay in sync with ``local_codex_lite.cli_parser``.

The reference doc is rendered by ``scripts/gen_cli_reference.py``; this test
re-renders it in memory and compares against the committed file so any CLI
change that forgets to regenerate the doc fails CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_cli_reference.py"
DOC_PATH = REPO_ROOT / "docs" / "cli-reference.md"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_cli_reference", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_doc_has_generation_markers() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "<!-- BEGIN GENERATED -->" in text
    assert "<!-- END GENERATED -->" in text


def test_cli_reference_doc_matches_parser() -> None:
    gen = _load_generator()
    existing = DOC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    rendered = gen.render_document(existing)
    assert rendered == existing, (
        "docs/cli-reference.md is out of date; run: python scripts/gen_cli_reference.py"
    )


def test_render_document_requires_markers() -> None:
    gen = _load_generator()
    with pytest.raises(ValueError, match="markers"):
        gen.render_document("# CLI reference\n\nno markers here\n")


def test_generated_section_is_deterministic() -> None:
    gen = _load_generator()
    assert gen.build_generated_section() == gen.build_generated_section()

"""Coverage for cli_utils.py — load_urls, normalize_suggested_commands,
looks_like_shell_command, load_evidence_block, load_rag_context, render_evidence_item."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from local_codex_lite.cli_utils import (
    load_evidence_block,
    load_rag_context,
    load_urls,
    looks_like_shell_command,
    normalize_suggested_commands,
    render_evidence_item,
)

# ---------------------------------------------------------------------------
# load_urls — repo_file, repo_urls, deduplication
# ---------------------------------------------------------------------------


def test_load_urls_reads_file_skipping_comments_and_blanks(tmp_path: Path) -> None:
    repo_file = tmp_path / "urls.txt"
    repo_file.write_text(
        "# a comment\n\nhttps://example.com/repo1\nhttps://example.com/repo2\n",
        encoding="utf-8",
    )
    result = load_urls(str(repo_file), None)
    assert result == ["https://example.com/repo1", "https://example.com/repo2"]


def test_load_urls_deduplicates_preserving_order(tmp_path: Path) -> None:
    repo_file = tmp_path / "urls.txt"
    repo_file.write_text("https://a.com\nhttps://b.com\n", encoding="utf-8")
    result = load_urls(str(repo_file), ["https://a.com", "https://c.com"])
    assert result == ["https://a.com", "https://b.com", "https://c.com"]


def test_load_urls_with_only_repo_urls() -> None:
    result = load_urls(None, ["https://x.com", "https://y.com"])
    assert result == ["https://x.com", "https://y.com"]


def test_load_urls_returns_empty_list_when_both_none() -> None:
    assert load_urls(None, None) == []


# ---------------------------------------------------------------------------
# normalize_suggested_commands — non-list commands and non-dict item
# ---------------------------------------------------------------------------


def test_normalize_suggested_commands_non_list_commands_value() -> None:
    result = normalize_suggested_commands({"commands": "not a list"})
    assert result == {"commands": []}


def test_normalize_suggested_commands_none_commands_value() -> None:
    result = normalize_suggested_commands({"commands": None})
    assert result == {"commands": []}


def test_normalize_suggested_commands_skips_non_dict_non_string_items() -> None:
    result = normalize_suggested_commands({"commands": [42, None, {"cmd": "pytest"}]})
    # 42 and None are not dict or string → skipped; {"cmd": "pytest"} is a valid command
    cmds = result["commands"]
    assert len(cmds) == 1
    assert cmds[0]["cmd"] == "pytest"


def test_normalize_suggested_commands_skips_non_shell_bare_string() -> None:
    result = normalize_suggested_commands(["Implement the feature properly."])
    assert result == {"commands": []}


# ---------------------------------------------------------------------------
# looks_like_shell_command — sentence-like string with punctuation → False
# ---------------------------------------------------------------------------


def test_looks_like_shell_command_returns_false_for_sentence() -> None:
    assert looks_like_shell_command("Implement the full feature.") is False


def test_looks_like_shell_command_returns_false_for_question() -> None:
    assert looks_like_shell_command("Check if this works?") is False


def test_looks_like_shell_command_returns_false_for_start_keyword() -> None:
    assert looks_like_shell_command("test the integration now") is False


def test_looks_like_shell_command_returns_true_for_real_command() -> None:
    assert looks_like_shell_command("pytest tests/ -q") is True


# ---------------------------------------------------------------------------
# load_evidence_block — non-existent file raises SystemExit
# ---------------------------------------------------------------------------


def test_load_evidence_block_raises_for_nonexistent_file(tmp_path: Path) -> None:
    missing = tmp_path / "no_such.txt"
    with pytest.raises(SystemExit, match="Evidence file not found"):
        load_evidence_block([str(missing)])


# ---------------------------------------------------------------------------
# load_evidence_block — directory path → rglobs all files
# ---------------------------------------------------------------------------


def test_load_evidence_block_loads_files_from_directory(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "a.txt").write_text("content a\n", encoding="utf-8")
    (evidence_dir / "b.txt").write_text("content b\n", encoding="utf-8")
    result = load_evidence_block([str(evidence_dir)])
    assert "content a" in result
    assert "content b" in result


# ---------------------------------------------------------------------------
# load_rag_context — RagProviderError, empty result, non-empty result
# ---------------------------------------------------------------------------


def test_load_rag_context_returns_empty_on_rag_provider_error(tmp_path: Path) -> None:
    from local_codex_lite.config import load_config
    from local_codex_lite.rag import RagProviderError

    cfg = load_config(tmp_path)
    with patch("local_codex_lite.cli_utils.retrieve_rag_context", side_effect=RagProviderError("err")):
        result = load_rag_context(tmp_path, cfg, "query")
    assert result == ""


def test_load_rag_context_returns_empty_when_no_chunks(tmp_path: Path) -> None:
    from local_codex_lite.config import load_config

    cfg = load_config(tmp_path)
    with patch("local_codex_lite.cli_utils.retrieve_rag_context", return_value=[]):
        result = load_rag_context(tmp_path, cfg, "query")
    assert result == ""


def test_load_rag_context_returns_formatted_context(tmp_path: Path) -> None:
    from local_codex_lite.config import load_config

    cfg = load_config(tmp_path)
    fake_chunks = [object()]
    with patch("local_codex_lite.cli_utils.retrieve_rag_context", return_value=fake_chunks):
        with patch("local_codex_lite.cli_utils.format_retrieved_context", return_value="ctx") as mock_fmt:
            result = load_rag_context(tmp_path, cfg, "query")
    assert result == "ctx"
    mock_fmt.assert_called_once_with(fake_chunks, cfg.rag.max_context_chars)


# ---------------------------------------------------------------------------
# render_evidence_item — OSError and empty text
# ---------------------------------------------------------------------------


def test_render_evidence_item_returns_empty_string_on_oserror(tmp_path: Path) -> None:
    p = tmp_path / "unreadable.txt"
    p.write_text("data\n", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
        result = render_evidence_item(p)
    assert result == ""


def test_render_evidence_item_returns_empty_string_for_blank_file(tmp_path: Path) -> None:
    p = tmp_path / "blank.txt"
    p.write_text("   \n\n  \n", encoding="utf-8")
    result = render_evidence_item(p)
    assert result == ""


# ---------------------------------------------------------------------------
# read_stdin_evidence — empty and blank stdin
# ---------------------------------------------------------------------------


def test_read_stdin_evidence_raises_on_empty_stdin() -> None:
    from local_codex_lite.cli_utils import read_stdin_evidence

    fake_stdin = io.StringIO("")
    fake_stdin.isatty = lambda: False  # type: ignore[method-assign]
    with patch("local_codex_lite.cli_utils.sys.stdin", fake_stdin):
        with pytest.raises(SystemExit, match="No piped evidence"):
            read_stdin_evidence()


def test_read_stdin_evidence_raises_on_blank_stdin() -> None:
    from local_codex_lite.cli_utils import read_stdin_evidence

    fake_stdin = io.StringIO("   \n  \n")
    fake_stdin.isatty = lambda: False  # type: ignore[method-assign]
    with patch("local_codex_lite.cli_utils.sys.stdin", fake_stdin):
        with pytest.raises(SystemExit, match="Empty evidence"):
            read_stdin_evidence()


def test_read_stdin_evidence_raises_when_isatty(tmp_path: Path) -> None:
    from local_codex_lite.cli_utils import read_stdin_evidence

    fake_stdin = io.StringIO("")
    fake_stdin.isatty = lambda: True  # type: ignore[method-assign]
    with patch("local_codex_lite.cli_utils.sys.stdin", fake_stdin):
        with pytest.raises(SystemExit, match="No stdin available"):
            read_stdin_evidence()

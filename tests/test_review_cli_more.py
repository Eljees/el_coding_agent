"""Branch coverage for cli_review: diff acquisition, context building and the
cmd_review error paths that test_review_cli.py does not exercise.  No git, no
LLM: subprocess and the planner are always monkeypatched."""

from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path

import pytest

from local_codex_lite import cli, cli_review
from local_codex_lite.config import UnknownProfileError


class _Chunk:
    def __init__(self, path: Path, content: str) -> None:
        self.path = path
        self.content = content


def _review_args(**overrides) -> argparse.Namespace:
    base = {
        "base": "",
        "head": "HEAD",
        "staged": False,
        "diff_file": [],
        "diff_stdin": False,
        "profile": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _patch_review_io(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli_review, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli_review, "load_config", lambda root: cli.default_config())
    monkeypatch.setattr(
        cli_review, "session_dir", lambda root: tmp_path / ".local-codex-lite" / "runs" / "run-1"
    )
    monkeypatch.setattr(
        cli_review, "create_evidence_bundle", lambda *args, **kwargs: tmp_path / "bundle"
    )
    monkeypatch.setattr(cli_review, "save_raw_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "save_summary_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "save_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "write_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "dump_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_review, "dump_json", lambda *args, **kwargs: None)


# ---------------------------------------------------------------------------
# _load_review_diff
# ---------------------------------------------------------------------------


def test_load_review_diff_resolves_relative_diff_file(tmp_path: Path) -> None:
    (tmp_path / "x.diff").write_text("DIFF-CONTENT", encoding="utf-8")
    args = _review_args(diff_file=["x.diff", "missing.diff"])

    text, label = cli_review._load_review_diff(tmp_path, args)

    assert text == "DIFF-CONTENT"
    assert label == "diff-file"


def test_load_review_diff_reads_stdin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_review.sys, "stdin", io.StringIO("STDIN-DIFF"))
    args = _review_args(diff_stdin=True)

    text, label = cli_review._load_review_diff(tmp_path, args)

    assert text == "STDIN-DIFF"
    assert label == "stdin"


def test_load_review_diff_base_head_range(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, list[str]] = {}

    def fake_git_diff(root: Path, git_args: list[str]) -> str:
        seen["git_args"] = git_args
        return "RANGE-DIFF"

    monkeypatch.setattr(cli_review, "_git_diff", fake_git_diff)
    args = _review_args(base="main", head="")

    text, label = cli_review._load_review_diff(tmp_path, args)

    assert text == "RANGE-DIFF"
    assert label == "main...HEAD"
    assert "main...HEAD" in seen["git_args"]


def test_load_review_diff_staged(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, list[str]] = {}

    def fake_git_diff(root: Path, git_args: list[str]) -> str:
        seen["git_args"] = git_args
        return "STAGED-DIFF"

    monkeypatch.setattr(cli_review, "_git_diff", fake_git_diff)
    args = _review_args(staged=True)

    text, label = cli_review._load_review_diff(tmp_path, args)

    assert (text, label) == ("STAGED-DIFF", "staged")
    assert "--cached" in seen["git_args"]


def test_load_review_diff_working_tree_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_review, "_git_diff", lambda root, git_args: "WT-DIFF")

    text, label = cli_review._load_review_diff(tmp_path, _review_args())

    assert (text, label) == ("WT-DIFF", "working tree")


# ---------------------------------------------------------------------------
# _git_diff
# ---------------------------------------------------------------------------


def test_git_diff_returns_stdout_on_success(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, cwd=None, capture_output=False, text=False, check=False):
        assert cmd[0] == "git"
        return subprocess.CompletedProcess(cmd, 0, stdout="GIT-OUT", stderr="")

    monkeypatch.setattr(cli_review, "subprocess_run", fake_run)

    assert cli_review._git_diff(tmp_path, ["diff"]) == "GIT-OUT"


def test_git_diff_raises_on_failure(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, cwd=None, capture_output=False, text=False, check=False):
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: not a repo")

    monkeypatch.setattr(cli_review, "subprocess_run", fake_run)

    with pytest.raises(RuntimeError, match="not a repo"):
        cli_review._git_diff(tmp_path, ["diff"])


# ---------------------------------------------------------------------------
# _extract_review_paths / _build_review_context
# ---------------------------------------------------------------------------


def test_extract_review_paths_skips_dev_null_and_dupes() -> None:
    diff = "\n".join(
        [
            "--- a/src/x.py",
            "+++ b/src/x.py",
            "--- a//dev/null",
            "+++ b/src/x.py",
        ]
    )

    paths = cli_review._extract_review_paths(diff)

    assert paths == [Path("src/x.py")]


def test_build_review_context_handles_unreadable_root(tmp_path: Path) -> None:
    context = cli_review._build_review_context(tmp_path / "missing", "DIFF", [], [])

    assert "# Review summary" in context
    assert "# Top-level entries" not in context
    assert "DIFF" in context


def test_build_review_context_includes_file_excerpts(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    chunk = _Chunk(tmp_path / "src" / "app.py", "print('hi')")

    context = cli_review._build_review_context(tmp_path, "DIFF", [Path("src/app.py")], [chunk])

    assert "# Current file excerpts" in context
    assert "## src/app.py" in context
    assert "print('hi')" in context


# ---------------------------------------------------------------------------
# cmd_review error / context paths
# ---------------------------------------------------------------------------


def test_cmd_review_unknown_profile_returns_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_review, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(cli_review, "load_config", lambda root: cli.default_config())

    def fake_apply_profile(cfg, profile_name):
        raise UnknownProfileError("Unknown LLM profile 'missing'")

    monkeypatch.setattr(cli_review, "apply_profile", fake_apply_profile)

    result = cli_review.cmd_review(_review_args(profile="missing"))

    assert result == 1
    assert "Unknown LLM profile" in capsys.readouterr().out


def test_cmd_review_empty_diff_returns_1(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_review_io(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_review, "_load_review_diff", lambda root, args: ("   \n", "stdin"))

    result = cli_review.cmd_review(_review_args())

    assert result == 1
    assert "No diff found" in capsys.readouterr().out


def test_cmd_review_saves_context_for_selected_files(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_review_io(monkeypatch, tmp_path)
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        cli_review,
        "save_summary_json",
        lambda bundle, name, payload: saved.setdefault(name, payload),
    )
    diff = "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    monkeypatch.setattr(cli_review, "_load_review_diff", lambda root, args: (diff, "working tree"))
    monkeypatch.setattr(
        cli_review,
        "read_file_chunks",
        lambda *args, **kwargs: [_Chunk(tmp_path / "src" / "app.py", "new content")],
    )
    monkeypatch.setattr(
        cli_review,
        "make_review",
        lambda *args, **kwargs: {
            "summary": "ok",
            "overall_risk": "low",
            "findings": [],
            "positives": [],
            "missing_context": [],
            "recommendation": "approve",
        },
    )

    result = cli_review.cmd_review(_review_args())

    out = capsys.readouterr().out
    assert result == 0
    assert "Code review" in out
    context_payload = saved["review_context.json"]
    assert isinstance(context_payload, list)
    assert context_payload[0]["path"] == "src/app.py"
    assert "review.json" in saved

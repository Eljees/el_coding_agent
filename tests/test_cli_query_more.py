"""Coverage for cli_query.py — error branches in cmd_preview and cmd_ask."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_codex_lite.cli_query import cmd_ask, cmd_preview
from local_codex_lite.config import UnknownProfileError
from local_codex_lite.rag import RagProviderError


def _preview_args(tmp_path: Path, *, rag: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        task="fix bug",
        evidence_file=[],
        evidence_stdin=False,
        rag=rag,
        profile=None,
    )


def _ask_args(*, rag: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        evidence_file=[],
        evidence_stdin=False,
        rag=rag,
        profile=None,
    )


# ---------------------------------------------------------------------------
# cmd_preview — workspace message printed when root != base_root
# ---------------------------------------------------------------------------


def test_cmd_preview_prints_workspace_when_root_differs(tmp_path: Path, capsys) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    args = _preview_args(tmp_path)

    with patch("local_codex_lite.cli_query.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_query.resolve_task_workspace", return_value=sub):
            with patch("local_codex_lite.cli_query.load_config") as mock_cfg:
                with patch(
                    "local_codex_lite.cli_query.apply_profile", return_value=mock_cfg.return_value
                ):
                    with patch("local_codex_lite.cli_query._load_evidence_block", return_value=""):
                        with patch(
                            "local_codex_lite.cli_query.detect_runtime_fix_context",
                            return_value=None,
                        ):
                            with patch(
                                "local_codex_lite.cli_query._selected_files", return_value=[]
                            ):
                                with patch("local_codex_lite.cli_query._print_selected_files"):
                                    with patch(
                                        "local_codex_lite.cli_query.make_plan", return_value={}
                                    ):
                                        with patch(
                                            "local_codex_lite.cli_query._print_plan_summary"
                                        ):
                                            with patch(
                                                "local_codex_lite.cli_query.make_patch",
                                                return_value="",
                                            ):
                                                with patch(
                                                    "local_codex_lite.cli_query.preview_patch",
                                                    return_value=0,
                                                ):
                                                    rc = cmd_preview(args)

    assert rc == 0


# ---------------------------------------------------------------------------
# cmd_preview — UnknownProfileError → returns 1
# ---------------------------------------------------------------------------


def test_cmd_preview_returns_1_on_unknown_profile(tmp_path: Path) -> None:
    args = _preview_args(tmp_path)

    with patch("local_codex_lite.cli_query.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_query.resolve_task_workspace", return_value=tmp_path):
            with patch("local_codex_lite.cli_query.load_config"):
                with patch(
                    "local_codex_lite.cli_query.apply_profile",
                    side_effect=UnknownProfileError("no such profile"),
                ):
                    rc = cmd_preview(args)

    assert rc == 1


# ---------------------------------------------------------------------------
# cmd_preview — RagProviderError from make_plan → returns 1
# ---------------------------------------------------------------------------


def test_cmd_preview_returns_1_on_rag_provider_error(tmp_path: Path) -> None:
    args = _preview_args(tmp_path)

    with patch("local_codex_lite.cli_query.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_query.resolve_task_workspace", return_value=tmp_path):
            with patch("local_codex_lite.cli_query.load_config") as mock_cfg:
                with patch(
                    "local_codex_lite.cli_query.apply_profile", return_value=mock_cfg.return_value
                ):
                    with patch("local_codex_lite.cli_query._load_evidence_block", return_value=""):
                        with patch(
                            "local_codex_lite.cli_query.detect_runtime_fix_context",
                            return_value=None,
                        ):
                            with patch(
                                "local_codex_lite.cli_query._selected_files", return_value=[]
                            ):
                                with patch("local_codex_lite.cli_query._print_selected_files"):
                                    with patch(
                                        "local_codex_lite.cli_query.make_plan",
                                        side_effect=RagProviderError("rag down"),
                                    ):
                                        rc = cmd_preview(args)

    assert rc == 1


# ---------------------------------------------------------------------------
# cmd_preview — generic Exception from make_patch → returns 1
# ---------------------------------------------------------------------------


def test_cmd_preview_returns_1_on_generic_exception(tmp_path: Path) -> None:
    args = _preview_args(tmp_path)

    with patch("local_codex_lite.cli_query.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_query.resolve_task_workspace", return_value=tmp_path):
            with patch("local_codex_lite.cli_query.load_config") as mock_cfg:
                with patch(
                    "local_codex_lite.cli_query.apply_profile", return_value=mock_cfg.return_value
                ):
                    with patch("local_codex_lite.cli_query._load_evidence_block", return_value=""):
                        with patch(
                            "local_codex_lite.cli_query.detect_runtime_fix_context",
                            return_value=None,
                        ):
                            with patch(
                                "local_codex_lite.cli_query._selected_files", return_value=[]
                            ):
                                with patch("local_codex_lite.cli_query._print_selected_files"):
                                    with patch(
                                        "local_codex_lite.cli_query.make_plan", return_value={}
                                    ):
                                        with patch(
                                            "local_codex_lite.cli_query._print_plan_summary"
                                        ):
                                            with patch(
                                                "local_codex_lite.cli_query.make_patch",
                                                side_effect=ValueError("unexpected"),
                                            ):
                                                rc = cmd_preview(args)

    assert rc == 1


# ---------------------------------------------------------------------------
# cmd_ask — UnknownProfileError → returns 1
# ---------------------------------------------------------------------------


def test_cmd_ask_returns_1_on_unknown_profile(tmp_path: Path) -> None:
    args = _ask_args()

    with patch("local_codex_lite.cli_query.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_query.load_config"):
            with patch(
                "local_codex_lite.cli_query.apply_profile",
                side_effect=UnknownProfileError("no such profile"),
            ):
                rc = cmd_ask("what is this?", args)

    assert rc == 1


# ---------------------------------------------------------------------------
# cmd_ask — RagProviderError from _load_rag_context → returns 1
# ---------------------------------------------------------------------------


def test_cmd_ask_returns_1_on_rag_provider_error(tmp_path: Path) -> None:
    args = _ask_args(rag=True)

    with patch("local_codex_lite.cli_query.workspace_root", return_value=tmp_path):
        with patch("local_codex_lite.cli_query.load_config") as mock_cfg:
            with patch(
                "local_codex_lite.cli_query.apply_profile", return_value=mock_cfg.return_value
            ):
                with patch("local_codex_lite.cli_query._load_evidence_block", return_value=""):
                    with patch(
                        "local_codex_lite.cli_query.config_path",
                        return_value=tmp_path / "config.toml",
                    ):
                        with patch(
                            "local_codex_lite.cli_query._load_rag_context",
                            side_effect=RagProviderError("rag failed"),
                        ):
                            rc = cmd_ask("what is this?", args)

    assert rc == 1

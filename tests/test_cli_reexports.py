"""Guard for the cli.py re-export surface.

cli.py split its handlers across cli_parser/cli_review/cli_logs/cli_rag/cli_info
but keeps re-exporting them (and the historical ``_underscore`` helpers) for the
test-suite and external callers.  The ruff F401 + isort autofix happily strips
any re-export that is not internally used and not pinned in ``__all__``; this
test makes such an accidental drop fail loudly instead of silently breaking a
``cli.<name>`` monkeypatch somewhere else.
"""

from __future__ import annotations

from local_codex_lite import cli


def test_every_dunder_all_name_is_importable() -> None:
    missing = [name for name in cli.__all__ if not hasattr(cli, name)]
    assert not missing, f"cli.__all__ lists names not bound on the module: {missing}"


def test_command_handlers_are_re_exported() -> None:
    # The dispatcher in cli.main() and the test-suite reach these through cli.*
    for name in (
        "cmd_init",
        "cmd_status",
        "cmd_config_show",
        "cmd_recognize",
        "cmd_review",
        "cmd_logs_latest",
        "cmd_logs_diff",
        "cmd_rag_index",
        "cmd_rag_query",
        "build_parser",
        "_run_task",
        "default_config",
    ):
        assert hasattr(cli, name), name

"""Coverage for rich_compat.py (RichConsole branch) and targeting.py (OSError)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# targeting.py:61-62 — OSError in _normalize_candidate
# ---------------------------------------------------------------------------


def test_normalize_candidate_returns_none_on_oserror(tmp_path: Path) -> None:
    from local_codex_lite.targeting import _normalize_candidate

    with patch.object(Path, "is_absolute", side_effect=OSError("bad path")):
        result = _normalize_candidate("test.py", tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# rich_compat.py:74-76 — make_console when RichConsole is available
# ---------------------------------------------------------------------------


def test_make_console_with_rich_available() -> None:
    import local_codex_lite.rich_compat as rc

    fake_console_cls = MagicMock(return_value=MagicMock())
    with patch.object(rc, "RichConsole", fake_console_cls):
        c1 = rc.make_console()
        c2 = rc.make_console(legacy_windows=True)

    fake_console_cls.assert_any_call()
    fake_console_cls.assert_any_call(legacy_windows=True)
    assert c1 is not None
    assert c2 is not None


# ---------------------------------------------------------------------------
# rich_compat.py:82 — make_table when RichTable is available
# ---------------------------------------------------------------------------


def test_make_table_with_rich_available() -> None:
    import local_codex_lite.rich_compat as rc

    fake_table_cls = MagicMock(return_value=MagicMock())
    with patch.object(rc, "RichConsole", MagicMock()):
        with patch.object(rc, "RichTable", fake_table_cls):
            t = rc.make_table("My Table")

    fake_table_cls.assert_called_once_with(title="My Table")
    assert t is not None

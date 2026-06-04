"""Cover the stdlib fallback in rich_compat (used when the optional `rich`
extra is absent).  The fallback classes are exercised directly so the tests do
not depend on whether `rich` happens to be installed.
"""

from __future__ import annotations

from local_codex_lite import rich_compat
from local_codex_lite.rich_compat import SimpleConsole, SimpleTable, make_console, make_table


def test_simple_console_drops_rich_only_kwargs(capsys) -> None:
    SimpleConsole().print("hello", highlight=False, style="bold")  # rich-only kwargs dropped
    assert capsys.readouterr().out == "hello\n"


def test_simple_console_keeps_builtin_kwargs(capsys) -> None:
    SimpleConsole().print("a", "b", sep="-", end="!")
    assert capsys.readouterr().out == "a-b!"


def test_print_json_string(capsys) -> None:
    SimpleConsole().print_json('{"a": 1}')
    assert '"a": 1' in capsys.readouterr().out


def test_print_json_dict(capsys) -> None:
    SimpleConsole().print_json({"b": 2})
    assert '"b": 2' in capsys.readouterr().out


def test_print_json_invalid_falls_back_to_raw(capsys) -> None:
    SimpleConsole().print_json("not json")
    assert capsys.readouterr().out == "not json\n"


def test_simple_table_render() -> None:
    t = SimpleTable(title="Report")
    t.add_column("Name")
    t.add_column("Status")
    t.add_row("alpha", "OK")
    t.add_row("beta", "FAIL", "extra")  # more cells than columns -> width grows
    out = str(t)
    assert "Report" in out
    assert "Name" in out and "Status" in out
    assert "alpha" in out and "beta" in out and "extra" in out


def test_make_console_fallback_when_rich_absent(monkeypatch) -> None:
    monkeypatch.setattr(rich_compat, "RichConsole", None)
    assert isinstance(make_console(), SimpleConsole)
    assert isinstance(make_console(legacy_windows=True), SimpleConsole)


def test_make_table_fallback_when_rich_absent(monkeypatch) -> None:
    monkeypatch.setattr(rich_compat, "RichTable", None)
    assert isinstance(make_table("t"), SimpleTable)

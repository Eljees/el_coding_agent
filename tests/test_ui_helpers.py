"""Mock-Tk tests for local_codex_lite.ui_helpers (audit D14).

No real Tk root or display is needed: a small FakeText stand-in records the
widget calls the helpers make, and ``tkinter.Menu`` is monkeypatched with a
recorder so the context-menu builders can be exercised headlessly.
"""

from __future__ import annotations

import tkinter
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from local_codex_lite import ui_helpers


class FakeText:
    """Minimal tk.Text stand-in recording every interaction."""

    def __init__(self, text: str = "", state: str = "normal", selection: str | None = None):
        self.text = text
        self.state = state
        self.selection = selection
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.bindings: dict[str, Any] = {}
        self.state_history: list[str] = []

    def cget(self, key: str) -> str:
        assert key == "state"
        return self.state

    def configure(self, **kwargs: Any) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]
            self.state_history.append(kwargs["state"])

    def tag_add(self, *args: Any) -> None:
        self.calls.append(("tag_add", args))

    def mark_set(self, *args: Any) -> None:
        self.calls.append(("mark_set", args))

    def see(self, *args: Any) -> None:
        self.calls.append(("see", args))

    def get(self, start: str, end: str) -> str:
        if start == "sel.first":
            if self.selection is None:
                raise tkinter.TclError("text doesn't contain any characters tagged with sel")
            return self.selection
        return self.text

    def bind(self, sequence: str, func: Any) -> None:
        self.bindings[sequence] = func

    def event_generate(self, sequence: str) -> None:
        self.calls.append(("event_generate", (sequence,)))

    def delete(self, start: str, end: str) -> None:
        self.calls.append(("delete", (start, end)))
        self.text = ""


class FakeMenu:
    """Recorder standing in for tkinter.Menu."""

    instances: ClassVar[list[FakeMenu]] = []

    def __init__(self, master: Any, tearoff: int = 0):
        self.master = master
        self.tearoff = tearoff
        self.commands: dict[str, Any] = {}
        self.popup_at: tuple[int, int] | None = None
        FakeMenu.instances.append(self)

    def add_command(self, label: str, command: Any) -> None:
        self.commands[label] = command

    def tk_popup(self, x: int, y: int) -> None:
        self.popup_at = (x, y)


@pytest.fixture(autouse=True)
def _fake_menu(monkeypatch: pytest.MonkeyPatch):
    FakeMenu.instances = []
    monkeypatch.setattr(tkinter, "Menu", FakeMenu)
    yield


def _event() -> Any:
    return SimpleNamespace(x_root=111, y_root=222)


# ---------------------------------------------------------------------------
# select_all_text / get_widget_text
# ---------------------------------------------------------------------------


def test_select_all_text_normal_widget() -> None:
    widget = FakeText(text="hello")
    assert ui_helpers.select_all_text(widget) == "break"
    assert ("tag_add", ("sel", "1.0", "end-1c")) in widget.calls
    assert ("mark_set", ("insert", "1.0")) in widget.calls
    assert ("see", ("1.0",)) in widget.calls
    assert widget.state_history == []  # state never touched


def test_select_all_text_disabled_widget_restores_state() -> None:
    widget = FakeText(text="hello", state="disabled")
    assert ui_helpers.select_all_text(widget) == "break"
    assert widget.state_history == ["normal", "disabled"]
    assert widget.state == "disabled"


def test_get_widget_text_normal() -> None:
    widget = FakeText(text="content here")
    assert ui_helpers.get_widget_text(widget) == "content here"
    assert widget.state_history == []


def test_get_widget_text_disabled_restores_state() -> None:
    widget = FakeText(text="ro content", state="disabled")
    assert ui_helpers.get_widget_text(widget) == "ro content"
    assert widget.state_history == ["normal", "disabled"]
    assert widget.state == "disabled"


# ---------------------------------------------------------------------------
# copy_selection_or_all
# ---------------------------------------------------------------------------


def test_copy_selection_uses_selection_when_present() -> None:
    widget = FakeText(text="all text", selection="sel text")
    copied: list[str] = []
    fallback: list[bool] = []
    rc = ui_helpers.copy_selection_or_all(widget, lambda: fallback.append(True), copied.append)
    assert rc == "break"
    assert copied == ["sel text"]
    assert fallback == []


def test_copy_selection_falls_back_without_selection() -> None:
    widget = FakeText(text="all text", selection=None)
    copied: list[str] = []
    fallback: list[bool] = []
    rc = ui_helpers.copy_selection_or_all(widget, lambda: fallback.append(True), copied.append)
    assert rc == "break"
    assert copied == []
    assert fallback == [True]


# ---------------------------------------------------------------------------
# context menus
# ---------------------------------------------------------------------------


def test_show_text_context_menu_builds_and_pops() -> None:
    widget = FakeText()
    rc = ui_helpers.show_text_context_menu(
        widget, lambda: None, lambda: "break", lambda: "break", _event()
    )
    assert rc == "break"
    (menu,) = FakeMenu.instances
    assert list(menu.commands) == ["Copy selection", "Copy all", "Select all"]
    assert menu.popup_at == (111, 222)


def test_show_editable_text_context_menu_commands_work() -> None:
    widget = FakeText(text="abc")
    rc = ui_helpers.show_editable_text_context_menu(widget, _event())
    assert rc == "break"
    (menu,) = FakeMenu.instances
    assert list(menu.commands) == ["Copy selection", "Paste", "Select all", "Clear"]
    assert menu.popup_at == (111, 222)

    menu.commands["Copy selection"]()
    assert ("event_generate", ("<<Copy>>",)) in widget.calls
    menu.commands["Paste"]()
    assert ("event_generate", ("<<Paste>>",)) in widget.calls
    menu.commands["Select all"]()
    assert ("tag_add", ("sel", "1.0", "end-1c")) in widget.calls
    menu.commands["Clear"]()
    assert ("delete", ("1.0", "end")) in widget.calls
    assert widget.text == ""


# ---------------------------------------------------------------------------
# make_readonly_copyable / make_editable_copyable
# ---------------------------------------------------------------------------


def test_make_readonly_copyable_wires_bindings() -> None:
    widget = FakeText(text="x")
    copy_calls: list[bool] = []
    sel_calls: list[bool] = []
    all_calls: list[bool] = []

    ui_helpers.make_readonly_copyable(
        widget,
        lambda: copy_calls.append(True),
        lambda: (sel_calls.append(True), "break")[1],
        lambda: (all_calls.append(True), "break")[1],
    )
    assert widget.state == "disabled"
    assert set(widget.bindings) == {
        "<Control-c>",
        "<Control-a>",
        "<Command-c>",
        "<Command-a>",
        "<Button-3>",
    }
    widget.bindings["<Control-c>"](None)
    widget.bindings["<Command-c>"](None)
    assert len(sel_calls) == 2
    widget.bindings["<Control-a>"](None)
    widget.bindings["<Command-a>"](None)
    assert len(all_calls) == 2

    rc = widget.bindings["<Button-3>"](_event())
    assert rc == "break"
    (menu,) = FakeMenu.instances
    menu.commands["Copy all"]()
    assert copy_calls == [True]


def test_make_editable_copyable_wires_bindings() -> None:
    widget = FakeText(text="x")
    all_calls: list[bool] = []

    ui_helpers.make_editable_copyable(widget, lambda: (all_calls.append(True), "break")[1])
    assert set(widget.bindings) == {"<Control-a>", "<Command-a>", "<Button-3>"}
    widget.bindings["<Control-a>"](None)
    assert all_calls == [True]

    rc = widget.bindings["<Button-3>"](_event())
    assert rc == "break"
    (menu,) = FakeMenu.instances
    assert "Paste" in menu.commands

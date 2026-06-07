"""Tk-free widget utility helpers for CommandCenterUI.

These functions operate on tk.Text widgets without referencing any
CommandCenterUI-specific state.  Extracted here so the logic is findable
and can be tested (or mocked) independently of the Tk event loop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk


def select_all_text(widget: tk.Text) -> str:
    """Select all text in *widget*, temporarily enabling it if read-only.

    Returns ``"break"`` so callers can pass this function as a Tk event handler.
    """
    prior_state = str(widget.cget("state"))
    if prior_state == "disabled":
        widget.configure(state="normal")
    widget.tag_add("sel", "1.0", "end-1c")
    widget.mark_set("insert", "1.0")
    widget.see("1.0")
    if prior_state == "disabled":
        widget.configure(state="disabled")
    return "break"


def get_widget_text(widget: tk.Text) -> str:
    """Return the full text content of *widget* regardless of its state."""
    prior_state = str(widget.cget("state"))
    if prior_state == "disabled":
        widget.configure(state="normal")
    text = widget.get("1.0", "end-1c")
    if prior_state == "disabled":
        widget.configure(state="disabled")
    return text


def copy_selection_or_all(
    widget: tk.Text,
    copy_callback: Callable[[], None],
    copy_text_fn: Callable[[str], None],
) -> str:
    """Copy the active selection; fall back to *copy_callback* when none.

    Returns ``"break"``.
    """
    try:
        selected = widget.get("sel.first", "sel.last")
    except Exception:  # tk.TclError when there is no selection
        copy_callback()
        return "break"
    copy_text_fn(selected)
    return "break"


def show_text_context_menu(
    widget: tk.Text,
    copy_callback: Callable[[], None],
    copy_sel_fn: Callable[[], str],
    select_all_fn: Callable[[], str],
    event: tk.Event,
) -> str:
    """Pop up a right-click context menu for a read-only text widget."""
    import tkinter as _tk

    menu = _tk.Menu(widget, tearoff=0)
    menu.add_command(label="Copy selection", command=copy_sel_fn)
    menu.add_command(label="Copy all", command=copy_callback)
    menu.add_command(label="Select all", command=select_all_fn)
    menu.tk_popup(event.x_root, event.y_root)
    return "break"


def show_editable_text_context_menu(
    widget: tk.Text,
    event: tk.Event,
) -> str:
    """Pop up a right-click context menu for an editable text widget."""
    import tkinter as _tk

    menu = _tk.Menu(widget, tearoff=0)
    menu.add_command(
        label="Copy selection",
        command=lambda: widget.event_generate("<<Copy>>"),
    )
    menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
    menu.add_command(label="Select all", command=lambda: select_all_text(widget))
    menu.add_command(label="Clear", command=lambda: widget.delete("1.0", "end"))
    menu.tk_popup(event.x_root, event.y_root)
    return "break"


def make_readonly_copyable(
    widget: tk.Text,
    copy_callback: Callable[[], None],
    copy_sel_fn: Callable[[], str],
    select_all_fn: Callable[[], str],
) -> None:
    """Configure *widget* as read-only with Ctrl+C, Ctrl+A and right-click support."""
    widget.configure(state="disabled")
    widget.bind("<Control-c>", lambda _e: copy_sel_fn())
    widget.bind("<Control-a>", lambda _e: select_all_fn())
    widget.bind("<Command-c>", lambda _e: copy_sel_fn())
    widget.bind("<Command-a>", lambda _e: select_all_fn())
    widget.bind(
        "<Button-3>",
        lambda event: show_text_context_menu(
            widget, copy_callback, copy_sel_fn, select_all_fn, event
        ),
    )


def make_editable_copyable(
    widget: tk.Text,
    select_all_fn: Callable[[], str],
) -> None:
    """Wire Ctrl+A and right-click helpers onto an editable *widget*."""
    widget.bind("<Control-a>", lambda _e: select_all_fn())
    widget.bind("<Command-a>", lambda _e: select_all_fn())
    widget.bind(
        "<Button-3>",
        lambda event: show_editable_text_context_menu(widget, event),
    )

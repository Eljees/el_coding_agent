"""Headless / minimal-display tests for local_codex_lite.ui.

Skip guard: tests requiring a live Tk display are marked @needs_display
and skipped on headless Linux runners.  On Windows a display is always
available; on Linux CI only if DISPLAY or WAYLAND_DISPLAY is set.

Note on Tk instance lifecycle: calling root.mainloop() then root.destroy()
shuts down the Tcl interpreter, preventing a second tk.Tk() in the same
process.  All tests here share ONE withdrawn Tk root via the ui_app fixture
so the interpreter stays alive.  The run_command_center_ui success path
(which calls mainloop) carries # pragma: no cover for this reason.
"""

from __future__ import annotations

import os
import sys

import pytest

import local_codex_lite.ui as ui_module

# ---------------------------------------------------------------------------
# Skip condition
# ---------------------------------------------------------------------------
_DISPLAY_AVAILABLE = (
    sys.platform == "win32"
    or bool(os.environ.get("DISPLAY"))
    or bool(os.environ.get("WAYLAND_DISPLAY"))
)

needs_display = pytest.mark.skipif(
    not _DISPLAY_AVAILABLE,
    reason="GUI tests require an active display (DISPLAY/WAYLAND_DISPLAY or Windows)",
)


# ---------------------------------------------------------------------------
# No-tkinter early-exit (does NOT require a display)
# ---------------------------------------------------------------------------


def test_run_command_center_ui_returns_1_when_tk_unavailable(capsys):
    """run_command_center_ui must print an error and return 1 when tk is None."""
    original_tk = ui_module.tk
    original_err = ui_module._TK_IMPORT_ERROR
    try:
        ui_module.tk = None
        ui_module._TK_IMPORT_ERROR = ImportError("no tkinter installed")
        rc = ui_module.run_command_center_ui()
    finally:
        ui_module.tk = original_tk
        ui_module._TK_IMPORT_ERROR = original_err
    assert rc == 1
    assert "Tkinter is not available" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Shared withdrawn Tk root (module-scoped — one Tk interpreter per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ui_app(tmp_path_factory):
    """Module-scoped withdrawn Tk root + CommandCenterUI for method tests.

    We use a single Tk() instance for the whole module because calling
    mainloop()+destroy() shuts down the Tcl interpreter, making a second
    Tk() impossible in the same process.
    """
    if not _DISPLAY_AVAILABLE:
        pytest.skip("no display available")
    tk = pytest.importorskip("tkinter")
    tmp = tmp_path_factory.mktemp("ui_headless")
    orig_cwd = os.getcwd()
    os.chdir(tmp)
    root = tk.Tk()
    root.withdraw()
    app = ui_module.CommandCenterUI(root)
    yield root, app
    try:
        root.destroy()
    except Exception:
        pass
    os.chdir(orig_cwd)


# ---------------------------------------------------------------------------
# Structural / initial state
# ---------------------------------------------------------------------------


@needs_display
def test_ui_initial_state(ui_app):
    _, app = ui_app
    assert app._busy is False
    assert app._preview_ready is False
    assert isinstance(app._task_history, list)
    assert app.capabilities is not None
    assert app.tools is not None


# ---------------------------------------------------------------------------
# _assume_clarification
# ---------------------------------------------------------------------------


@needs_display
def test_assume_clarification_default(ui_app):
    """clarify_var=False (default) → _assume_clarification() returns True."""
    _, app = ui_app
    app.clarify_var.set(False)
    assert app._assume_clarification() is True


@needs_display
def test_assume_clarification_clarify_on(ui_app):
    """clarify_var=True → _assume_clarification() returns False."""
    _, app = ui_app
    app.clarify_var.set(True)
    assert app._assume_clarification() is False
    app.clarify_var.set(False)


@needs_display
def test_clarify_assume_once_overrides(ui_app):
    """_clarify_assume_once=True makes _assume_clarification True even with clarify_var."""
    _, app = ui_app
    app.clarify_var.set(True)
    app._clarify_assume_once = True
    assert app._assume_clarification() is True
    app.clarify_var.set(False)
    app._clarify_assume_once = False


# ---------------------------------------------------------------------------
# Widget text accessors
# ---------------------------------------------------------------------------


@needs_display
def test_task_text_read(ui_app):
    """_task() returns stripped content of the task text widget."""
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.task_text.insert("1.0", "  fix the bug  ")
    assert app._task() == "fix the bug"
    app.task_text.delete("1.0", "end")


@needs_display
def test_evidence_text_read(ui_app):
    """_evidence() returns stripped content of the evidence text widget."""
    _, app = ui_app
    app.evidence_text.delete("1.0", "end")
    app.evidence_text.insert("1.0", "traceback here")
    assert app._evidence() == "traceback here"
    app.evidence_text.delete("1.0", "end")


# ---------------------------------------------------------------------------
# Output cache helpers
# ---------------------------------------------------------------------------


@needs_display
def test_write_command_output(ui_app):
    _, app = ui_app
    app._write_command_output("hello output")
    assert app._command_output_cache == "hello output"


@needs_display
def test_append_command_output(ui_app):
    _, app = ui_app
    app._write_command_output("line one")
    app._append_command_output("line two")
    assert "line one" in app._command_output_cache
    assert "line two" in app._command_output_cache


# ---------------------------------------------------------------------------
# Clipboard helpers
# ---------------------------------------------------------------------------


@needs_display
def test_copy_text_clipboard(ui_app):
    """_copy_text must place the string on the Tk clipboard."""
    root, app = ui_app
    app._copy_text("clipboard content")
    assert root.clipboard_get() == "clipboard content"


@needs_display
def test_copy_command_output(ui_app):
    root, app = ui_app
    app._write_command_output("cmd output text")
    app._copy_command_output()
    assert root.clipboard_get() == "cmd output text"


@needs_display
def test_copy_intent_output(ui_app):
    root, app = ui_app
    app._intent_output_cache = "intent json"
    app._copy_intent_output()
    assert root.clipboard_get() == "intent json"


@needs_display
def test_copy_all_output(ui_app):
    root, app = ui_app
    app._intent_output_cache = "intent part"
    app._write_command_output("cmd part")
    app._copy_all_output()
    combined = root.clipboard_get()
    assert "intent part" in combined or "cmd part" in combined


# ---------------------------------------------------------------------------
# Evidence widget helpers
# ---------------------------------------------------------------------------


@needs_display
def test_clear_evidence(ui_app):
    _, app = ui_app
    app.evidence_text.insert("1.0", "something")
    app._clear_evidence()
    assert app._evidence() == ""


@needs_display
def test_paste_evidence_from_clipboard(ui_app):
    """_paste_evidence inserts clipboard content into evidence widget."""
    root, app = ui_app
    root.clipboard_clear()
    root.clipboard_append("pasted content")
    app.evidence_text.delete("1.0", "end")
    app._paste_evidence()
    assert "pasted content" in app._evidence()
    app.evidence_text.delete("1.0", "end")


@needs_display
def test_paste_evidence_empty_clipboard(ui_app):
    """_paste_evidence with empty clipboard writes an error message."""
    root, app = ui_app
    root.clipboard_clear()
    app._write_command_output("")
    app._paste_evidence()
    assert "Clipboard" in app._command_output_cache


# ---------------------------------------------------------------------------
# Chat helpers
# ---------------------------------------------------------------------------


@needs_display
def test_chat_clear(ui_app):
    _, app = ui_app
    app._chat_messages.append({"role": "user", "content": "hello"})
    app._chat_clear()
    assert app._chat_messages == []


@needs_display
def test_chat_send_empty_input_does_nothing(ui_app):
    """_chat_send with no text in chat_input must not spawn a thread."""
    _, app = ui_app
    app.chat_input.delete("1.0", "end")
    before = len(app._chat_messages)
    app._chat_send()
    assert len(app._chat_messages) == before


# ---------------------------------------------------------------------------
# Button handlers (empty-task guard paths)
# ---------------------------------------------------------------------------


@needs_display
def test_analyze_empty_task(ui_app):
    """analyze() with empty task text must write an error message."""
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.analyze()
    assert "Enter a task first" in app._command_output_cache


@needs_display
def test_preview_empty_task(ui_app):
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.preview()
    assert "Enter a task first" in app._command_output_cache


@needs_display
def test_apply_changes_empty_task(ui_app):
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.apply_changes()
    assert "Enter a task first" in app._command_output_cache


@needs_display
def test_exec_changes_empty_task(ui_app):
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.exec_changes()
    assert "Enter a task first" in app._command_output_cache


# ---------------------------------------------------------------------------
# Miscellaneous state / helpers
# ---------------------------------------------------------------------------


@needs_display
def test_update_action_buttons_idle(ui_app):
    """_update_action_buttons must not raise when not busy."""
    _, app = ui_app
    app._busy = False
    app._last_decision = None
    app._preview_ready = False
    app._update_action_buttons()


@needs_display
def test_stop_worker_sets_flag(ui_app):
    _, app = ui_app
    app._stop_triggered = False
    app._stop_button.configure(state="normal")
    app._stop_worker()
    assert app._stop_triggered is True
    app._stop_triggered = False


@needs_display
def test_refresh_runs_list_no_runs(ui_app):
    """_refresh_runs_list must not raise when workspace has no runs."""
    _, app = ui_app
    app._refresh_runs_list()


@needs_display
def test_refresh_history_combo(ui_app):
    _, app = ui_app
    app._refresh_history_combo()


@needs_display
def test_initial_progress_message(ui_app):
    """_initial_progress_message must return a non-empty string."""
    _, app = ui_app
    msg = app._initial_progress_message("preview", "fix the bug")
    assert isinstance(msg, str) and len(msg) > 0


@needs_display
def test_worker_for_action_returns_callable(ui_app):
    """_worker_for_action must return a callable for every action kind."""
    from local_codex_lite.ui_commands import BackgroundAction

    _, app = ui_app
    for kind, extra in [
        ("preview", {}),
        ("run", {"apply": False, "exec_": False}),
        ("cve", {}),
        ("appsechub", {}),
        ("artifact", {"extract": False}),
    ]:
        action = BackgroundAction(
            kind=kind,
            label=kind,
            apply=extra.get("apply", False),
            exec_=extra.get("exec_", False),
            extract=extra.get("extract", False),
        )
        worker = app._worker_for_action(action)
        assert callable(worker), f"_worker_for_action({kind!r}) must return callable"


@needs_display
def test_logs_latest_queues_background(ui_app):
    """logs_latest() must not raise (starts a background worker thread)."""
    _, app = ui_app
    app.logs_latest()


# ---------------------------------------------------------------------------
# Runs-tab helpers
# ---------------------------------------------------------------------------


@needs_display
def test_show_run_timeline_empty_selection(ui_app):
    """_show_run_timeline with no listbox selection must return early."""
    _, app = ui_app
    app.runs_list.selection_clear(0, "end")
    app._show_run_timeline()


@needs_display
def test_copy_runs_detail(ui_app):
    root, app = ui_app
    app._copy_runs_detail()
    root.clipboard_get()  # verify clipboard was touched without raising


# ---------------------------------------------------------------------------
# History combo
# ---------------------------------------------------------------------------


@needs_display
def test_on_history_select_out_of_range(ui_app):
    """_on_history_select with combobox.current() == -1 must return early."""
    _, app = ui_app
    app._on_history_select()  # current() returns -1 (nothing selected) → return


@needs_display
def test_on_history_select_valid_index(ui_app):
    """_on_history_select with valid idx inserts task into task_text."""
    _, app = ui_app
    app._task_history = ["task alpha", "task beta"]
    app._refresh_history_combo()
    app._history_combo.current(0)
    app._on_history_select()
    assert "task alpha" in app._task()
    app.task_text.delete("1.0", "end")


# ---------------------------------------------------------------------------
# Export output
# ---------------------------------------------------------------------------


@needs_display
def test_export_output_empty_content(ui_app):
    """_export_output returns early when command output cache is empty."""
    _, app = ui_app
    app._write_command_output("")
    app._export_output()  # must not raise or open filedialog


# ---------------------------------------------------------------------------
# Chat: response + append helpers
# ---------------------------------------------------------------------------


@needs_display
def test_chat_on_response(ui_app):
    """_chat_on_response must append to chat_messages and restore send button."""
    _, app = ui_app
    app._chat_messages.clear()
    app._chat_send_button.configure(state="disabled")
    app._chat_on_response("model answer")
    assert app._chat_messages == [{"role": "assistant", "content": "model answer"}]
    app._chat_messages.clear()


@needs_display
def test_chat_append(ui_app):
    """_chat_append must write role header + text to chat_history widget."""
    from local_codex_lite import ui_helpers

    _, app = ui_app
    app._chat_append("User", "greetings")
    content = ui_helpers.get_widget_text(app.chat_history)
    assert "[User]" in content
    assert "greetings" in content


# ---------------------------------------------------------------------------
# Intent panel
# ---------------------------------------------------------------------------


@needs_display
def test_write_intent_populates_vars(ui_app):
    """_write_intent must set _last_decision and update status vars."""
    from local_codex_lite.intent import recognize_intent

    _, app = ui_app
    decision = recognize_intent("покажи логи", app.capabilities)
    app._write_intent(decision)
    assert app._last_decision is decision


# ---------------------------------------------------------------------------
# Capability / tool / skill detail selectors
# ---------------------------------------------------------------------------


@needs_display
def test_show_capability_detail_empty_selection(ui_app):
    _, app = ui_app
    app.capability_list.selection_clear(0, "end")
    app._show_capability_detail()  # returns early


@needs_display
def test_show_tool_detail_empty_selection(ui_app):
    _, app = ui_app
    app.tool_list.selection_clear(0, "end")
    app._show_tool_detail()


@needs_display
def test_show_skill_detail_no_skills(ui_app):
    _, app = ui_app
    app.skill_list.selection_clear(0, "end")
    app._show_skill_detail()


@needs_display
def test_copy_capability_detail(ui_app):
    root, app = ui_app
    app._copy_capability_detail()
    root.clipboard_get()


# ---------------------------------------------------------------------------
# analyze() — synchronous, exercises intent + workspace + history
# ---------------------------------------------------------------------------


@needs_display
def test_analyze_with_task(ui_app):
    """analyze() with task text must write command output without raising."""
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.task_text.insert("1.0", "покажи логи")
    app.analyze()
    assert app._command_output_cache  # something was written
    app.task_text.delete("1.0", "end")


# ---------------------------------------------------------------------------
# _finish_background (direct call — no mainloop needed)
# ---------------------------------------------------------------------------


@needs_display
def test_finish_background_normal_output(ui_app):
    """_finish_background without stop_triggered must write output to cache."""
    _, app = ui_app
    app._busy = True
    app._stop_triggered = False
    app._busy_started_at = 0.0
    app._finish_background("worker result")
    assert app._busy is False
    assert "worker result" in app._command_output_cache


@needs_display
def test_finish_background_stopped(ui_app):
    """_finish_background with stop_triggered must write 'Stopped by user.'."""
    _, app = ui_app
    app._busy = True
    app._stop_triggered = True
    app._finish_background("ignored")
    assert app._busy is False
    assert "Stopped by user." in app._command_output_cache


# ---------------------------------------------------------------------------
# _maybe_ask_clarifications early-exit paths
# ---------------------------------------------------------------------------


@needs_display
def test_maybe_ask_clarifications_clarify_off(ui_app):
    """clarify_var=False → _maybe_ask_clarifications returns immediately."""
    _, app = ui_app
    app.clarify_var.set(False)
    app._maybe_ask_clarifications("output with clarifications?")


@needs_display
def test_maybe_ask_clarifications_no_background(ui_app):
    """_last_background is None → returns before inspecting output."""
    _, app = ui_app
    app.clarify_var.set(True)
    app._clarify_assume_once = False
    app._last_background = None
    app._maybe_ask_clarifications("output")
    app.clarify_var.set(False)


@needs_display
def test_maybe_ask_clarifications_wrong_label(ui_app):
    """label not in preview/apply set → returns early without opening dialog."""
    _, app = ui_app
    app.clarify_var.set(True)
    app._clarify_assume_once = False
    app._last_background = ("logs latest", "", None)
    app._maybe_ask_clarifications("output")
    app.clarify_var.set(False)
    app._last_background = None


@needs_display
def test_maybe_ask_clarifications_no_questions(ui_app):
    """output with no clarifying questions → returns without opening dialog."""
    _, app = ui_app
    app.clarify_var.set(True)
    app._clarify_assume_once = False
    app._last_background = ("preview", "some task", lambda t: "done")
    app._maybe_ask_clarifications("plain output without any questions")
    app.clarify_var.set(False)
    app._last_background = None


# ---------------------------------------------------------------------------
# _schedule_busy_heartbeat not-busy path
# ---------------------------------------------------------------------------


@needs_display
def test_schedule_busy_heartbeat_not_busy(ui_app):
    """_schedule_busy_heartbeat with _busy=False must return immediately."""
    _, app = ui_app
    app._busy = False
    app._schedule_busy_heartbeat()  # returns early at if not self._busy:


# ---------------------------------------------------------------------------
# _open_workspace_folder error path
# ---------------------------------------------------------------------------


@needs_display
def test_open_workspace_folder_startfile_error(ui_app, monkeypatch):
    """_open_workspace_folder handles OSError from os.startfile gracefully."""
    import os

    _, app = ui_app

    def _fail(path):
        raise OSError("no startfile")

    monkeypatch.setattr(os, "startfile", _fail)
    app._open_workspace_folder()
    assert "Could not open workspace folder" in app._command_output_cache


# ---------------------------------------------------------------------------
# _prepare_workspace (no project mode)
# ---------------------------------------------------------------------------


@needs_display
def test_prepare_workspace_base_mode(ui_app):
    """_prepare_workspace with project_mode=False resets active workspace to base."""
    from local_codex_lite.intent import recognize_intent

    _, app = ui_app
    app.project_mode_var.set(False)
    decision = recognize_intent("покажи логи", app.capabilities)
    base = app._base_workspace_root
    app._prepare_workspace("покажи логи", decision, create=False)
    assert app._active_workspace_root == base


# ---------------------------------------------------------------------------
# _paste_evidence with existing evidence (separator path)
# ---------------------------------------------------------------------------


@needs_display
def test_paste_evidence_with_existing_content(ui_app):
    """_paste_evidence with existing evidence inserts '\\n\\n' separator first."""
    root, app = ui_app
    root.clipboard_clear()
    root.clipboard_append("appended text")
    app.evidence_text.delete("1.0", "end")
    app.evidence_text.insert("1.0", "pre-existing")
    app._paste_evidence()
    content = app._evidence()
    assert "pre-existing" in content
    assert "appended text" in content
    app.evidence_text.delete("1.0", "end")

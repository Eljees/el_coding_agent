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


# ---------------------------------------------------------------------------
# Capability / tool listbox selection (covers the "item selected" paths)
# ---------------------------------------------------------------------------


@needs_display
def test_show_capability_detail_with_selection(ui_app):
    """_show_capability_detail with a selected capability must populate detail panel."""
    _, app = ui_app
    if not app.capabilities:
        pytest.skip("no capabilities discovered")
    app.capability_list.selection_set(0)
    app._show_capability_detail()  # covers the selection path
    app.capability_list.selection_clear(0, "end")


@needs_display
def test_show_tool_detail_with_selection(ui_app):
    """_show_tool_detail with a selected tool must populate detail panel."""
    _, app = ui_app
    if not app.tools:
        pytest.skip("no tools discovered")
    app.tool_list.selection_set(0)
    app._show_tool_detail()
    app.tool_list.selection_clear(0, "end")


# ---------------------------------------------------------------------------
# _schedule_busy_heartbeat busy path (calls root.after from main thread — safe)
# ---------------------------------------------------------------------------


@needs_display
def test_schedule_busy_heartbeat_busy(ui_app):
    """_schedule_busy_heartbeat with _busy=True must append heartbeat to output."""
    _, app = ui_app
    app._busy = True
    app._busy_started_at = 0.0
    app._busy_lines = []
    app._write_command_output("")
    app._schedule_busy_heartbeat()
    assert app._busy_lines  # at least one heartbeat line
    app._busy = False
    app._busy_lines = []


# ---------------------------------------------------------------------------
# preview() with task (covers preview body + _run_background "preview" branch)
# ---------------------------------------------------------------------------


@needs_display
def test_preview_with_task(ui_app):
    """preview() with task text must execute the preview body and start a background job."""
    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.task_text.insert("1.0", "покажи логи")
    app.preview()
    # background thread is daemonic and may fail at root.after, but the
    # main-thread preview body (write intent, save history, etc.) ran
    app.task_text.delete("1.0", "end")
    app._busy = False  # reset state touched by _run_background


# ---------------------------------------------------------------------------
# _export_output with content and cancelled filedialog
# ---------------------------------------------------------------------------


@needs_display
def test_export_output_filedialog_cancelled(ui_app, monkeypatch):
    """_export_output with content but cancelled dialog must not write any file."""
    import local_codex_lite.ui as _ui

    _, app = ui_app
    app._write_command_output("some output to export")
    monkeypatch.setattr(
        _ui, "filedialog", type("FD", (), {"asksaveasfilename": staticmethod(lambda **_: "")})()
    )
    app._export_output()  # filedialog returns "" → function returns early


# ---------------------------------------------------------------------------
# Worker wrappers (mocked ui_runners to avoid LLM calls)
# ---------------------------------------------------------------------------


@needs_display
def test_preview_worker_delegates_to_ui_runners(ui_app, monkeypatch):
    from unittest.mock import patch

    _, app = ui_app
    with patch("local_codex_lite.ui_runners.preview_worker", return_value="preview result") as m:
        result = app._preview_worker("fix bug")
    m.assert_called_once()
    assert result == "preview result"


@needs_display
def test_artifact_worker_delegates(ui_app, monkeypatch):
    from unittest.mock import patch

    _, app = ui_app
    with patch("local_codex_lite.ui_runners.artifact_worker", return_value="artifact ok") as m:
        result = app._artifact_worker("scan artifact", extract=False)
    m.assert_called_once()
    assert result == "artifact ok"


@needs_display
def test_cve_worker_delegates(ui_app, monkeypatch):
    from unittest.mock import patch

    _, app = ui_app
    with patch("local_codex_lite.ui_runners.cve_worker", return_value="cve ok") as m:
        result = app._cve_worker("scan cve")
    m.assert_called_once()
    assert result == "cve ok"


@needs_display
def test_appsechub_worker_delegates(ui_app):
    from unittest.mock import patch

    _, app = ui_app
    with patch("local_codex_lite.ui_runners.appsechub_worker", return_value="sec ok") as m:
        result = app._appsechub_worker("scan security")
    m.assert_called_once()
    assert result == "sec ok"


@needs_display
def test_run_worker_delegates(ui_app):
    from unittest.mock import patch

    _, app = ui_app
    with patch("local_codex_lite.ui_runners.run_worker", return_value="run ok") as m:
        result = app._run_worker("do something", apply=True, exec_=False)
    m.assert_called_once()
    assert result == "run ok"


# ---------------------------------------------------------------------------
# _refresh_runs_list with non-empty runs (covers the insert loop body)
# ---------------------------------------------------------------------------


@needs_display
def test_refresh_runs_list_with_runs(ui_app):
    """_refresh_runs_list with actual runs must insert each line into the listbox."""
    from unittest.mock import MagicMock, patch

    _, app = ui_app
    mock_ov = MagicMock()
    mock_ov.run_ids = ["run-a", "run-b"]
    mock_ov.lines = ["Run A — success", "Run B — fail"]
    with patch("local_codex_lite.ui_commands.runs_overview", return_value=mock_ov):
        app._refresh_runs_list()
    assert app.runs_list.size() == 2
    app.runs_list.delete(0, "end")
    app._runs_ids = []


# ---------------------------------------------------------------------------
# _show_run_timeline with a valid listbox selection
# ---------------------------------------------------------------------------


@needs_display
def test_show_run_timeline_with_selection(ui_app):
    """_show_run_timeline with a selected row must call run_timeline_text."""
    from unittest.mock import patch

    _, app = ui_app
    app.runs_list.insert("end", "Run 1")
    app._runs_ids = ["run-id-1"]
    app.runs_list.selection_set(0)
    with patch("local_codex_lite.ui_commands.run_timeline_text", return_value="timeline") as m:
        app._show_run_timeline()
    m.assert_called_once()
    app.runs_list.delete(0, "end")
    app._runs_ids = []


# ---------------------------------------------------------------------------
# _save_geometry (just must not raise)
# ---------------------------------------------------------------------------


@needs_display
def test_save_geometry(ui_app):
    """_save_geometry must persist the window geometry without raising."""
    _, app = ui_app
    app._save_geometry()


# ---------------------------------------------------------------------------
# _save_task_to_history with empty string (early-return path)
# ---------------------------------------------------------------------------


@needs_display
def test_save_task_to_history_empty_no_op(ui_app):
    """_save_task_to_history('') must return early without modifying history."""
    _, app = ui_app
    before = list(app._task_history)
    app._save_task_to_history("")
    assert list(app._task_history) == before


# ---------------------------------------------------------------------------
# _export_output: filedialog unavailable path
# ---------------------------------------------------------------------------


@needs_display
def test_export_output_filedialog_unavailable(ui_app):
    """_export_output with filedialog=None must return early without raising."""
    import local_codex_lite.ui as _ui

    _, app = ui_app
    app._command_output_cache = "some content"
    orig = _ui.filedialog
    _ui.filedialog = None
    try:
        app._export_output()
    finally:
        _ui.filedialog = orig


# ---------------------------------------------------------------------------
# _export_output: path returned but write fails (error appended to output)
# ---------------------------------------------------------------------------


@needs_display
def test_export_output_with_write_error(ui_app, monkeypatch):
    """_export_output must append the write error when export_output_text returns one."""
    from unittest.mock import patch

    import local_codex_lite.ui as _ui

    _, app = ui_app
    app._command_output_cache = "important output"
    fake_fd = type("FD", (), {"asksaveasfilename": staticmethod(lambda **_: "/tmp/out.txt")})()
    monkeypatch.setattr(_ui, "filedialog", fake_fd)
    with patch(
        "local_codex_lite.ui_commands.export_output_text",
        return_value="Write failed: permission denied",
    ):
        app._export_output()
    assert "Write failed" in app._command_output_cache


# ---------------------------------------------------------------------------
# _chat_send with content (dispatches thread; thread.start is mocked)
# ---------------------------------------------------------------------------


@needs_display
def test_chat_send_with_content_dispatches_worker(ui_app):
    """_chat_send with non-empty input must clear input, append message, start thread."""
    from unittest.mock import MagicMock, patch

    _, app = ui_app
    app.chat_input.delete("1.0", "end")
    app.chat_input.insert("1.0", "hello model")
    app._chat_messages.clear()
    mock_thread = MagicMock()
    with patch("threading.Thread", return_value=mock_thread):
        app._chat_send()
    mock_thread.start.assert_called_once()
    assert any(m.get("content") == "hello model" for m in app._chat_messages)
    assert app.chat_input.get("1.0", "end").strip() == ""
    # restore button state modified by _chat_send
    app._chat_messages.clear()
    app._chat_send_button.configure(state="normal")
    app._chat_status_var.set("")


# ---------------------------------------------------------------------------
# _chat_worker (calls ui_runners.chat_worker, registers root.after callback)
# ---------------------------------------------------------------------------


@needs_display
def test_chat_worker_calls_ui_runners(ui_app):
    """_chat_worker must delegate to ui_runners.chat_worker and schedule response."""
    from unittest.mock import patch

    root, app = ui_app
    with (
        patch("local_codex_lite.ui_runners.chat_worker", return_value="model answer") as m,
        patch.object(root, "after"),
    ):
        app._chat_worker([{"role": "user", "content": "hi"}])
    m.assert_called_once()


# ---------------------------------------------------------------------------
# _show_skill_detail with a valid selection
# ---------------------------------------------------------------------------


@needs_display
def test_show_skill_detail_with_selection(ui_app):
    """_show_skill_detail with a selected skill must call skill_detail_text."""
    from unittest.mock import MagicMock, patch

    _, app = ui_app
    mock_skill = MagicMock()
    app.skills = [mock_skill]
    app.skill_list.insert("end", "test_skill")
    app.skill_list.selection_set(0)
    with patch("local_codex_lite.ui_commands.skill_detail_text", return_value="skill detail") as m:
        app._show_skill_detail()
    m.assert_called_once_with(mock_skill)
    app.skill_list.delete(0, "end")


# ---------------------------------------------------------------------------
# apply_changes / exec_changes with task (mocking _run_background)
# ---------------------------------------------------------------------------


@needs_display
def test_apply_changes_with_task(ui_app):
    """apply_changes with a non-empty task must call _run_background."""
    from unittest.mock import patch

    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.task_text.insert("1.0", "fix the bug")
    with (
        patch.object(app, "_run_background") as m_run,
        patch.object(app, "_write_intent"),
        patch.object(app, "_save_task_to_history"),
    ):
        app.apply_changes()
    m_run.assert_called_once()
    app.task_text.delete("1.0", "end")


@needs_display
def test_exec_changes_with_task(ui_app):
    """exec_changes with a non-empty task must call _run_background."""
    from unittest.mock import patch

    _, app = ui_app
    app.task_text.delete("1.0", "end")
    app.task_text.insert("1.0", "run the script")
    with patch.object(app, "_run_background") as m_run, patch.object(app, "_save_task_to_history"):
        app.exec_changes()
    m_run.assert_called_once()
    app.task_text.delete("1.0", "end")


# ---------------------------------------------------------------------------
# _run_background: worker exception is caught and becomes the output
# ---------------------------------------------------------------------------


@needs_display
def test_run_background_worker_exception_shows_in_output(ui_app):
    """runner() except clause must format the exception as output text."""
    from unittest.mock import patch

    root, app = ui_app

    def raising_worker(task):
        raise ValueError("deliberate error for test")

    class _SyncThread:
        """Runs the thread target synchronously so we can assert the result inline."""

        def __init__(self, target=None, args=(), daemon=None, **_):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    def sync_after(delay, fn=None, *args):
        if delay == 0 and fn is not None:
            fn()

    with (
        patch("threading.Thread", _SyncThread),
        patch.object(root, "after", side_effect=sync_after),
    ):
        app._run_background("logs latest", "some task", raising_worker)

    assert "ValueError" in app._command_output_cache
    assert "deliberate error for test" in app._command_output_cache


# ---------------------------------------------------------------------------
# _maybe_ask_clarifications: dialog cancelled (qa_pairs is None → early return)
# ---------------------------------------------------------------------------


@needs_display
def test_maybe_ask_clarifications_dialog_cancelled(ui_app):
    """When _ask_clarifications returns None (cancel), re-run must not happen."""
    from unittest.mock import patch

    _, app = ui_app
    app.clarify_var.set(True)
    app._clarify_assume_once = False
    app._last_background = ("preview", "fix bug", lambda t: "result")
    with (
        patch("local_codex_lite.ui_commands.extract_clarifying_questions", return_value=["Q1?"]),
        patch.object(app, "_ask_clarifications", return_value=None),
        patch.object(app, "_run_background") as m_run,
    ):
        app._maybe_ask_clarifications("CLARIFICATION REQUIRED")
    m_run.assert_not_called()
    app.clarify_var.set(False)
    app._last_background = None


# ---------------------------------------------------------------------------
# _maybe_ask_clarifications: answers provided → evidence inserted, re-run
# ---------------------------------------------------------------------------


@needs_display
def test_maybe_ask_clarifications_with_answers_reruns(ui_app):
    """When _ask_clarifications returns pairs, evidence is appended and re-run starts."""
    from unittest.mock import patch

    _, app = ui_app
    app.clarify_var.set(True)
    app._clarify_assume_once = False
    app._last_background = ("preview", "fix bug", lambda t: "result")
    app.evidence_text.delete("1.0", "end")
    app.evidence_text.insert("1.0", "pre-existing evidence")

    with (
        patch("local_codex_lite.ui_commands.extract_clarifying_questions", return_value=["Q1?"]),
        patch.object(app, "_ask_clarifications", return_value=[("Q1?", "A1")]),
        patch("local_codex_lite.ui_commands.clarification_evidence_block", return_value="[Q1?] A1"),
        patch.object(app, "_run_background") as m_run,
    ):
        app._maybe_ask_clarifications("CLARIFICATION REQUIRED\nQ1?")

    m_run.assert_called_once()
    assert app._clarify_assume_once is True
    app.clarify_var.set(False)
    app._last_background = None
    app._clarify_assume_once = False
    app.evidence_text.delete("1.0", "end")


# ---------------------------------------------------------------------------
# _ask_clarifications: modal dialog — cancel path (dialog destroyed → None)
# ---------------------------------------------------------------------------


@needs_display
def test_ask_clarifications_cancel(ui_app):
    """Destroying the dialog without clicking OK must return None."""
    import tkinter as tk

    root, app = ui_app

    def close_dialog():
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
                break

    root.after(100, close_dialog)
    result = app._ask_clarifications(["What is the deadline?"])
    assert result is None


# ---------------------------------------------------------------------------
# _ask_clarifications: modal dialog — OK path (entries → (question, answer) pairs)
# ---------------------------------------------------------------------------


@needs_display
def test_ask_clarifications_ok(ui_app):
    """Clicking OK must return (question, answer) pairs with 'use a reasonable default' fallback."""
    import tkinter as tk

    root, app = ui_app

    def click_ok():
        for child in root.winfo_children():
            if not isinstance(child, tk.Toplevel):
                continue

            def _find_and_invoke_ok(widget):
                for c in widget.winfo_children():
                    try:
                        if c.cget("text") == "OK":
                            c.invoke()
                            return True
                    except Exception:
                        pass
                    if _find_and_invoke_ok(c):
                        return True
                return False

            _find_and_invoke_ok(child)
            break

    root.after(100, click_ok)
    result = app._ask_clarifications(["What color?"])
    assert result is not None
    assert result[0][0] == "What color?"
    assert result[0][1] == "use a reasonable default"


# ---------------------------------------------------------------------------
# _prepare_workspace: project mode, create=True (workspace created)
# ---------------------------------------------------------------------------


@needs_display
def test_prepare_workspace_project_mode_create(ui_app):
    """_prepare_workspace in project mode with create=True must call create_project_workspace."""
    from unittest.mock import patch

    from local_codex_lite.task_heuristics import WorkspacePlan

    _, app = ui_app
    app._active_workspace_root = app._base_workspace_root
    app._active_workspace_task = ""

    with (
        patch(
            "local_codex_lite.ui.plan_workspace",
            return_value=WorkspacePlan(use_project=True, needs_new=True),
        ),
        patch("local_codex_lite.ui.create_project_workspace", return_value="/new/ws") as m_create,
        patch("local_codex_lite.ui_commands.workspace_status", return_value="ws: /new"),
    ):
        app._prepare_workspace("fix the bug", None, create=True)

    m_create.assert_called_once()
    assert app._active_workspace_root == "/new/ws"
    assert app._active_workspace_task == "fix the bug"
    # cleanup
    app._active_workspace_root = app._base_workspace_root
    app._active_workspace_task = ""

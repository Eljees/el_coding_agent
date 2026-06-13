from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:  # pragma: no cover — only reachable when tkinter is absent
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = exc  # type: Exception | None
else:
    _TK_IMPORT_ERROR = None

from . import ui_commands, ui_helpers, ui_runners
from .capabilities import capability_brief_lines, discover_capabilities
from .intent import (
    IntentDecision,
    recognize_intent,
)
from .project_workspace import create_project_workspace
from .skill_registry import discover_skills, skill_brief_lines
from .task_heuristics import (
    format_duration,  # noqa: F401  # re-exported as ui.format_duration for tests/back-compat
    plan_workspace,
)
from .tool_registry import default_tools, tool_brief_lines
from .ui_state import (
    load_geometry,
    load_task_history,
    push_task,
    save_geometry,
    save_task_history,
)


class CommandCenterUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.capabilities = discover_capabilities()
        self.tools = default_tools()
        self.skills = discover_skills(Path.cwd())
        self._command_output_cache = ""
        self._intent_output_cache = ""
        self._last_decision: IntentDecision | None = None
        self._preview_ready = False
        self._busy = False
        self._stop_triggered = False
        self._base_workspace_root = Path.cwd().resolve()
        self._active_workspace_root = self._base_workspace_root
        self._active_workspace_task = ""
        self._busy_label = ""
        self._busy_started_at = 0.0
        self._busy_lines: list[str] = []
        # Chat conversation history
        self._chat_messages: list[dict[str, str]] = []
        # Runs tab: run ids parallel to the listbox lines
        self._runs_ids: list[str] = []
        # Task history
        self._task_history: list[str] = []
        # Smoke-run after apply (opt-in)
        self.smoke_var = tk.BooleanVar(value=False)
        # Ask clarifying questions instead of assuming defaults (opt-in)
        self.clarify_var = tk.BooleanVar(value=False)
        # Last background action (label, task, worker) for the clarification re-run
        self._last_background: tuple[str, str, object] | None = None
        # One-shot override: re-run with assume_clarification=True after answers
        self._clarify_assume_once = False
        # workspace_var created before _build so status bar can reference it
        self.workspace_var = tk.StringVar(
            value=ui_commands.workspace_status(self._base_workspace_root)
        )
        self._load_task_history()
        self._build()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.root.title("local-codex-lite command center")
        self.root.minsize(900, 600)
        self.root.resizable(True, True)

        # Restore saved geometry (or fall back to default)
        saved_geo = self._load_geometry()
        self.root.geometry(saved_geo or "1120x760")

        # Save geometry and clean up on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # --- Status bar (packed before main so it stays at the bottom) ---
        self._status_bar = ttk.Frame(self.root, relief="sunken", padding=(4, 2))
        self._status_bar.pack(side="bottom", fill="x")
        self._status_cve_var = tk.StringVar(value="cve-bin-tool: checking…")
        self._status_llm_var = tk.StringVar(value="LLM: checking…")
        ttk.Label(self._status_bar, textvariable=self._status_cve_var, anchor="w").pack(
            side="left", padx=(0, 4)
        )
        ttk.Separator(self._status_bar, orient="vertical").pack(side="left", fill="y", padx=4)
        ttk.Label(self._status_bar, textvariable=self._status_llm_var, anchor="w").pack(
            side="left", padx=(0, 4)
        )
        ttk.Separator(self._status_bar, orient="vertical").pack(side="left", fill="y", padx=4)
        ttk.Label(self._status_bar, textvariable=self.workspace_var, anchor="w").pack(side="left")
        threading.Thread(target=self._probe_status, daemon=True).start()

        # --- Notebook with Agent and Chat tabs ---
        main = ttk.Frame(self.root, padding=4)
        main.pack(fill="both", expand=True)

        self._notebook = ttk.Notebook(main)
        self._notebook.pack(fill="both", expand=True)

        agent_frame = ttk.Frame(self._notebook, padding=8)
        self._notebook.add(agent_frame, text="  Agent  ")

        chat_frame = ttk.Frame(self._notebook, padding=8)
        self._notebook.add(chat_frame, text="  Chat  ")

        runs_frame = ttk.Frame(self._notebook, padding=8)
        self._notebook.add(runs_frame, text="  Runs  ")

        self._build_agent_tab(agent_frame)
        self._build_chat_tab(chat_frame)
        self._build_runs_tab(runs_frame)

        # --- Global hotkeys ---
        # Ctrl+Enter = Preview, Ctrl+Shift+Enter = Apply, F5 = Analyze
        self.root.bind("<F5>", lambda _e: self.analyze())
        # task_text-level bindings take priority for agent hotkeys
        # (chat_input binds Ctrl+Return itself and returns "break")

        self._write_command_output(
            "Analyze a task to see the suggested intent and safe next action.\n\nHotkeys: F5=Analyze  Ctrl+Enter=Preview  Ctrl+Shift+Enter=Apply"
        )

    def _build_agent_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x")
        left = ttk.Frame(top)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(top, width=320)
        right.pack(side="right", fill="y", padx=(12, 0))

        # --- Task input with scrollbar ---
        ttk.Label(left, text="Human task").pack(anchor="w")
        task_frame = ttk.Frame(left)
        task_frame.pack(fill="x", expand=False, pady=(4, 0))
        self.task_text = tk.Text(task_frame, height=5, wrap="word")
        task_scroll = ttk.Scrollbar(task_frame, orient="vertical", command=self.task_text.yview)
        self.task_text.configure(yscrollcommand=task_scroll.set)
        self.task_text.pack(side="left", fill="both", expand=True)
        task_scroll.pack(side="right", fill="y")
        self._make_editable_copyable(self.task_text)
        # Hotkeys on task_text (return "break" to suppress default newline)
        self.task_text.bind("<Control-Return>", lambda _e: self.preview() or "break")  # type: ignore[func-returns-value]
        self.task_text.bind("<Control-Shift-Return>", lambda _e: self.apply_changes() or "break")  # type: ignore[func-returns-value]

        # --- Task history dropdown ---
        history_row = ttk.Frame(left)
        history_row.pack(fill="x", pady=(2, 6))
        ttk.Label(history_row, text="History:").pack(side="left", padx=(0, 4))
        self._history_var = tk.StringVar()
        self._history_combo = ttk.Combobox(
            history_row,
            textvariable=self._history_var,
            state="readonly",
            width=70,
        )
        self._history_combo.pack(side="left", fill="x", expand=True)
        self._history_combo.bind("<<ComboboxSelected>>", self._on_history_select)
        self._refresh_history_combo()

        # --- Evidence / traceback with scrollbar ---
        evidence_frame = ttk.LabelFrame(left, text="Evidence / traceback")
        evidence_frame.pack(fill="x", expand=False, pady=(0, 8))
        evidence_inner = ttk.Frame(evidence_frame)
        evidence_inner.pack(fill="x", expand=False, padx=6, pady=(6, 0))
        self.evidence_text = tk.Text(evidence_inner, height=8, wrap="word")
        evidence_scroll = ttk.Scrollbar(
            evidence_inner, orient="vertical", command=self.evidence_text.yview
        )
        self.evidence_text.configure(yscrollcommand=evidence_scroll.set)
        self.evidence_text.pack(side="left", fill="both", expand=True)
        evidence_scroll.pack(side="right", fill="y")
        self._make_editable_copyable(self.evidence_text)
        evidence_actions = ttk.Frame(evidence_frame)
        evidence_actions.pack(fill="x", padx=6, pady=(4, 6))
        ttk.Button(evidence_actions, text="Paste clipboard", command=self._paste_evidence).pack(
            side="left"
        )
        ttk.Button(evidence_actions, text="Clear evidence", command=self._clear_evidence).pack(
            side="left", padx=(6, 0)
        )

        # --- Action buttons + progressbar + stop ---
        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Analyze (F5)", command=self.analyze).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(buttons, text="Preview (Ctrl+↵)", command=self.preview).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(buttons, text="Logs Latest", command=self.logs_latest).pack(
            side="left", padx=(0, 6)
        )
        self.apply_button = ttk.Button(
            buttons, text="Apply (Ctrl+Shift+↵)", command=self.apply_changes, state="disabled"
        )
        self.apply_button.pack(side="left", padx=(0, 6))
        self.exec_button = ttk.Button(
            buttons, text="Exec", command=self.exec_changes, state="disabled"
        )
        self.exec_button.pack(side="left")
        ttk.Checkbutton(
            buttons,
            text="Smoke after apply",
            variable=self.smoke_var,
        ).pack(side="left", padx=(12, 0))
        # Stop + progressbar on right side
        self._stop_button = ttk.Button(
            buttons, text="Stop", command=self._stop_worker, state="disabled"
        )
        self._stop_button.pack(side="right", padx=(6, 0))
        self._progress = ttk.Progressbar(buttons, mode="indeterminate", length=100)
        self._progress.pack(side="right", padx=(6, 0))

        # --- Workspace row ---
        workspace_row = ttk.Frame(left)
        workspace_row.pack(fill="x", pady=(0, 8))
        self.project_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            workspace_row,
            text="Create dated project folder for new project tasks",
            variable=self.project_mode_var,
        ).pack(side="left")
        ttk.Checkbutton(
            workspace_row,
            text="Ask clarifying questions",
            variable=self.clarify_var,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(workspace_row, textvariable=self.workspace_var).pack(side="right")
        ttk.Button(
            workspace_row,
            text="Open workspace",
            command=self._open_workspace_folder,
        ).pack(side="right", padx=(0, 8))

        # --- Decision panel ---
        status = ttk.LabelFrame(left, text="Decision")
        status.pack(fill="x", pady=(0, 8))
        self.can_do_var = tk.StringVar(value="can do: -")
        self.requires_apply_var = tk.StringVar(value="requires apply: -")
        self.requires_exec_var = tk.StringVar(value="requires exec: -")
        self.missing_inputs_var = tk.StringVar(value="missing inputs: -")
        self.safe_action_var = tk.StringVar(value="safe next action: -")
        for var in (
            self.can_do_var,
            self.requires_apply_var,
            self.requires_exec_var,
            self.missing_inputs_var,
            self.safe_action_var,
        ):
            ttk.Label(status, textvariable=var).pack(anchor="w", padx=8, pady=1)

        # --- Output row: IntentDecision JSON + Command output (both with scrollbars) ---
        output_row = ttk.Frame(left)
        output_row.pack(fill="both", expand=True)

        intent_frame = ttk.LabelFrame(output_row, text="IntentDecision JSON")
        intent_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        intent_inner = ttk.Frame(intent_frame)
        intent_inner.pack(fill="both", expand=True)
        self.intent_text = tk.Text(intent_inner, wrap="word")
        intent_scroll = ttk.Scrollbar(
            intent_inner, orient="vertical", command=self.intent_text.yview
        )
        self.intent_text.configure(yscrollcommand=intent_scroll.set)
        self.intent_text.pack(side="left", fill="both", expand=True)
        intent_scroll.pack(side="right", fill="y")
        self._make_readonly_copyable(self.intent_text, self._copy_intent_output)

        command_frame = ttk.LabelFrame(output_row, text="Command output")
        command_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))
        command_inner = ttk.Frame(command_frame)
        command_inner.pack(fill="both", expand=True)
        self.command_text = tk.Text(command_inner, wrap="word")
        command_scroll = ttk.Scrollbar(
            command_inner, orient="vertical", command=self.command_text.yview
        )
        self.command_text.configure(yscrollcommand=command_scroll.set)
        self.command_text.pack(side="left", fill="both", expand=True)
        command_scroll.pack(side="right", fill="y")
        self._make_readonly_copyable(self.command_text, self._copy_command_output)

        command_actions = ttk.Frame(command_frame)
        command_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(command_actions, text="Copy output", command=self._copy_command_output).pack(
            side="left"
        )
        ttk.Button(command_actions, text="Copy all", command=self._copy_all_output).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(command_actions, text="Export…", command=self._export_output).pack(
            side="left", padx=(6, 0)
        )

        # --- Right panel: capabilities / tools / skills / detail ---
        ttk.Label(right, text="Known capabilities").pack(anchor="w")
        self.capability_list = tk.Listbox(right, height=9)
        self.capability_list.pack(fill="both", expand=True, pady=(4, 0))
        for line in capability_brief_lines(self.capabilities):
            self.capability_list.insert("end", line)

        ttk.Label(right, text="Available tools").pack(anchor="w", pady=(8, 0))
        self.tool_list = tk.Listbox(right, height=5)
        self.tool_list.pack(fill="x", expand=False, pady=(4, 0))
        for line in tool_brief_lines(self.tools):
            self.tool_list.insert("end", line)

        ttk.Label(right, text="Available skills").pack(anchor="w", pady=(8, 0))
        self.skill_list = tk.Listbox(right, height=4)
        self.skill_list.pack(fill="x", expand=False, pady=(4, 0))
        for line in skill_brief_lines(self.skills):
            self.skill_list.insert("end", line)

        detail_frame = ttk.Frame(right)
        detail_frame.pack(fill="both", expand=False, pady=(8, 0))
        self.capability_detail = tk.Text(detail_frame, height=12, wrap="word")
        detail_scroll = ttk.Scrollbar(
            detail_frame, orient="vertical", command=self.capability_detail.yview
        )
        self.capability_detail.configure(yscrollcommand=detail_scroll.set)
        self.capability_detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self._make_readonly_copyable(self.capability_detail, self._copy_capability_detail)

        self.capability_list.bind("<<ListboxSelect>>", self._show_capability_detail)
        self.tool_list.bind("<<ListboxSelect>>", self._show_tool_detail)
        self.skill_list.bind("<<ListboxSelect>>", self._show_skill_detail)
        if self.capability_list.size():
            self.capability_list.selection_set(0)
            self._show_capability_detail()

    def _build_chat_tab(self, parent: ttk.Frame) -> None:
        """Build the chat panel: conversation history + input field + Send button."""
        ttk.Label(
            parent,
            text="Ask the model a question about the code or task. Ctrl+Enter to send.",
        ).pack(anchor="w", pady=(0, 6))

        # History (scrollable, read-only)
        history_outer = ttk.LabelFrame(parent, text="Conversation")
        history_outer.pack(fill="both", expand=True)
        history_inner = ttk.Frame(history_outer)
        history_inner.pack(fill="both", expand=True, padx=4, pady=4)
        self.chat_history = tk.Text(history_inner, wrap="word", state="disabled")
        chat_hist_scroll = ttk.Scrollbar(
            history_inner, orient="vertical", command=self.chat_history.yview
        )
        self.chat_history.configure(yscrollcommand=chat_hist_scroll.set)
        self.chat_history.pack(side="left", fill="both", expand=True)
        chat_hist_scroll.pack(side="right", fill="y")
        self.chat_history.tag_configure("role", font=("TkDefaultFont", 9, "bold"))

        # Input area
        ttk.Label(parent, text="Your question:").pack(anchor="w", pady=(8, 2))
        input_outer = ttk.Frame(parent)
        input_outer.pack(fill="x")
        self.chat_input = tk.Text(input_outer, height=4, wrap="word")
        chat_input_scroll = ttk.Scrollbar(
            input_outer, orient="vertical", command=self.chat_input.yview
        )
        self.chat_input.configure(yscrollcommand=chat_input_scroll.set)
        self.chat_input.pack(side="left", fill="both", expand=True)
        chat_input_scroll.pack(side="right", fill="y")
        self._make_editable_copyable(self.chat_input)
        self.chat_input.bind("<Control-Return>", lambda _e: self._chat_send() or "break")  # type: ignore[func-returns-value]

        # Actions
        chat_actions = ttk.Frame(parent)
        chat_actions.pack(fill="x", pady=(6, 0))
        self._chat_send_button = ttk.Button(
            chat_actions, text="Send (Ctrl+Enter)", command=self._chat_send
        )
        self._chat_send_button.pack(side="left")
        ttk.Button(chat_actions, text="Clear history", command=self._chat_clear).pack(
            side="left", padx=(8, 0)
        )
        self._chat_status_var = tk.StringVar(value="")
        ttk.Label(chat_actions, textvariable=self._chat_status_var, foreground="gray").pack(
            side="left", padx=(12, 0)
        )

    def _build_runs_tab(self, parent: ttk.Frame) -> None:
        """Runs tab: recent runs of the active workspace + per-run attempt timeline.

        All content comes from pure helpers (``ui_commands.runs_overview`` /
        ``run_timeline_text`` on top of ``run_report``); this method only wires
        widgets and bindings.
        """
        ttk.Label(
            parent,
            text="Recent runs of the active workspace. Select a run to see its attempt timeline.",
        ).pack(anchor="w", pady=(0, 6))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        runs_list_frame = ttk.Frame(left)
        runs_list_frame.pack(fill="both", expand=True)
        self.runs_list = tk.Listbox(runs_list_frame, width=58)
        runs_scroll = ttk.Scrollbar(
            runs_list_frame, orient="vertical", command=self.runs_list.yview
        )
        self.runs_list.configure(yscrollcommand=runs_scroll.set)
        self.runs_list.pack(side="left", fill="both", expand=True)
        runs_scroll.pack(side="right", fill="y")
        self.runs_list.bind("<<ListboxSelect>>", self._show_run_timeline)
        ttk.Button(left, text="Refresh", command=self._refresh_runs_list).pack(
            anchor="w", pady=(6, 0)
        )

        right = ttk.Frame(body)
        right.pack(side="right", fill="both", expand=True, padx=(12, 0))
        self.runs_detail = tk.Text(right, wrap="word")
        runs_detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.runs_detail.yview)
        self.runs_detail.configure(yscrollcommand=runs_detail_scroll.set)
        self.runs_detail.pack(side="left", fill="both", expand=True)
        runs_detail_scroll.pack(side="right", fill="y")
        self._make_readonly_copyable(self.runs_detail, self._copy_runs_detail)

        self._refresh_runs_list()

    def _refresh_runs_list(self) -> None:
        overview = ui_commands.runs_overview(self._active_workspace_root)
        self._runs_ids = list(overview.run_ids)
        self.runs_list.delete(0, "end")
        for line in overview.lines:
            self.runs_list.insert("end", line)
        placeholder = (
            "Select a run to see its attempt timeline."
            if overview.lines
            else "No runs found in this workspace yet."
        )
        self._set_text(self.runs_detail, placeholder)

    def _show_run_timeline(self, *_args) -> None:
        index = self.runs_list.curselection()
        if not index or index[0] >= len(self._runs_ids):
            return
        text = ui_commands.run_timeline_text(self._active_workspace_root, self._runs_ids[index[0]])
        self._set_text(self.runs_detail, text)

    def _copy_runs_detail(self) -> None:
        self._copy_text(ui_helpers.get_widget_text(self.runs_detail))

    # ------------------------------------------------------------------
    # Persistence: geometry and task history
    # ------------------------------------------------------------------

    def _load_geometry(self) -> str | None:
        return load_geometry(self._base_workspace_root)

    def _save_geometry(self) -> None:
        save_geometry(self._base_workspace_root, self.root.geometry())

    def _load_task_history(self) -> None:
        self._task_history = load_task_history(self._base_workspace_root)

    def _save_task_to_history(self, task: str) -> None:
        if not task:
            return
        self._task_history = push_task(self._task_history, task)
        save_task_history(self._base_workspace_root, self._task_history)
        self._refresh_history_combo()

    def _refresh_history_combo(self) -> None:
        if not hasattr(self, "_history_combo"):
            return
        self._history_combo["values"] = ui_commands.history_labels(self._task_history)

    def _on_history_select(self, *_args) -> None:
        idx = self._history_combo.current()
        if idx < 0 or idx >= len(self._task_history):
            return
        task = self._task_history[idx]
        self.task_text.delete("1.0", "end")
        self.task_text.insert("1.0", task)
        self._history_combo.set("")

    def _on_close(self) -> None:
        self._save_geometry()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Stop worker
    # ------------------------------------------------------------------

    def _stop_worker(self) -> None:
        """Signal the running background task to be treated as stopped."""
        self._stop_triggered = True
        self._stop_button.configure(state="disabled")

    # ------------------------------------------------------------------
    # Export output
    # ------------------------------------------------------------------

    def _export_output(self) -> None:
        content = self._command_output_cache
        if not content:
            return
        if filedialog is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("Markdown", "*.md"), ("All files", "*.*")],
            initialfile="output.txt",
            title="Export command output",
        )
        if not path:
            return
        error = ui_commands.export_output_text(path, content)
        if error is not None:
            self._append_command_output(error)

    # ------------------------------------------------------------------
    # Status bar probe (background thread)
    # ------------------------------------------------------------------

    def _probe_status(self) -> None:
        cve_status = ui_runners.probe_cve_status()
        self.root.after(0, lambda s=cve_status: self._status_cve_var.set(s))  # type: ignore[misc]
        llm_status = ui_runners.probe_llm_status(self._base_workspace_root)
        self.root.after(0, lambda s=llm_status: self._status_llm_var.set(s))  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Chat handlers
    # ------------------------------------------------------------------

    def _chat_send(self) -> None:
        question = self.chat_input.get("1.0", "end").strip()
        if not question:
            return
        self.chat_input.delete("1.0", "end")
        self._chat_append("You", question)
        self._chat_status_var.set("Sending…")
        self._chat_send_button.configure(state="disabled")
        self._chat_messages.append({"role": "user", "content": question})
        threading.Thread(
            target=self._chat_worker, args=(list(self._chat_messages),), daemon=True
        ).start()

    def _chat_worker(self, messages: list[dict[str, str]]) -> None:
        answer = ui_runners.chat_worker(messages, self._active_workspace_root)
        self.root.after(0, lambda a=answer: self._chat_on_response(a))  # type: ignore[misc]

    def _chat_on_response(self, answer: str) -> None:
        self._chat_messages.append({"role": "assistant", "content": answer})
        self._chat_append("Model", answer)
        self._chat_status_var.set("")
        self._chat_send_button.configure(state="normal")

    def _chat_append(self, role: str, text: str) -> None:
        self.chat_history.configure(state="normal")
        if self.chat_history.get("1.0", "end-1c"):
            self.chat_history.insert("end", "\n\n")
        self.chat_history.insert("end", f"[{role}]\n", "role")
        self.chat_history.insert("end", text)
        self.chat_history.see("end")
        self.chat_history.configure(state="disabled")

    def _chat_clear(self) -> None:
        self._chat_messages.clear()
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", "end")
        self.chat_history.configure(state="disabled")
        self._chat_status_var.set("")

    # ------------------------------------------------------------------
    # Agent tab: accessors and output helpers
    # ------------------------------------------------------------------

    def _task(self) -> str:
        return self.task_text.get("1.0", "end").strip()

    def _evidence(self) -> str:
        return self.evidence_text.get("1.0", "end").strip()

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _write_command_output(self, content: str) -> None:
        self._command_output_cache = content
        self._set_text(self.command_text, content)

    def _append_command_output(self, content: str) -> None:
        self._write_command_output(ui_commands.append_output(self._command_output_cache, content))

    def _write_intent(self, decision: IntentDecision) -> None:
        self._last_decision = decision
        can_do, requires_apply, requires_exec, missing, safe_action = (
            ui_commands.decision_status_labels(decision)
        )
        self.can_do_var.set(can_do)
        self.requires_apply_var.set(requires_apply)
        self.requires_exec_var.set(requires_exec)
        self.missing_inputs_var.set(missing)
        self.safe_action_var.set(safe_action)
        self._intent_output_cache = ui_commands.decision_json(decision)
        self._set_text(self.intent_text, self._intent_output_cache)
        self._update_action_buttons()

    def _show_capability_detail(self, *_args) -> None:
        index = self.capability_list.curselection()
        if not index:
            return
        self.tool_list.selection_clear(0, "end")
        self.skill_list.selection_clear(0, "end")
        capability = self.capabilities[index[0]]
        self._set_text(self.capability_detail, ui_commands.capability_detail_text(capability))

    def _show_tool_detail(self, *_args) -> None:
        index = self.tool_list.curselection()
        if not index:
            return
        self.capability_list.selection_clear(0, "end")
        self.skill_list.selection_clear(0, "end")
        tool = self.tools[index[0]]
        self._set_text(self.capability_detail, ui_commands.tool_detail_text(tool))

    def _show_skill_detail(self, *_args) -> None:
        index = self.skill_list.curselection()
        if not index or not self.skills:
            return
        self.capability_list.selection_clear(0, "end")
        self.tool_list.selection_clear(0, "end")
        skill = self.skills[index[0]]
        self._set_text(self.capability_detail, ui_commands.skill_detail_text(skill))

    # ------------------------------------------------------------------
    # Agent tab: button handlers
    # ------------------------------------------------------------------

    def analyze(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._preview_ready = False
        decision = recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        self._prepare_workspace(task, decision, create=False)
        self._save_task_to_history(task)
        self._write_command_output(ui_commands.analyze_completed_message(decision))

    def preview(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._preview_ready = False
        self._clarify_assume_once = False
        decision = recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        self._save_task_to_history(task)
        action = ui_commands.action_for_preview(decision.intent)
        self._run_background(action.label, task, self._worker_for_action(action))

    def logs_latest(self) -> None:
        self._run_background("logs latest", "", self._logs_latest_worker)

    def apply_changes(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._clarify_assume_once = False
        decision = self._last_decision or recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        self._save_task_to_history(task)
        action = ui_commands.action_for_apply(decision.intent)
        self._run_background(action.label, task, self._worker_for_action(action))

    def exec_changes(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._clarify_assume_once = False
        self._save_task_to_history(task)
        action = ui_commands.action_for_exec()
        self._run_background(action.label, task, self._worker_for_action(action))

    def _worker_for_action(self, action: ui_commands.BackgroundAction):
        """Map a dispatched :class:`BackgroundAction` to a bound worker callable."""
        if action.kind == "artifact":
            return lambda current_task: self._artifact_worker(current_task, extract=action.extract)
        if action.kind == "cve":
            return self._cve_worker
        if action.kind == "appsechub":
            return self._appsechub_worker
        if action.kind == "preview":
            return self._preview_worker
        return lambda current_task: self._run_worker(
            current_task, apply=action.apply, exec_=action.exec_
        )

    # ------------------------------------------------------------------
    # Background worker infrastructure
    # ------------------------------------------------------------------

    def _run_background(self, label: str, task: str, worker) -> None:
        self._last_background = (label, task, worker)
        if label in {"preview", "apply", "apply + exec"}:
            decision = self._last_decision or recognize_intent(task, self.capabilities)
            self._prepare_workspace(task, decision, create=True)
        self._busy = True
        self._stop_triggered = False
        self._busy_label = label
        self._busy_started_at = time.time()
        self._busy_lines = []
        self._update_action_buttons()
        # Start progress animation
        self._progress.start(10)
        self._stop_button.configure(state="normal")
        initial = self._initial_progress_message(label, task)
        self._write_command_output(initial)
        self._schedule_busy_heartbeat()

        def runner() -> None:
            try:
                output = worker(task)
            except Exception as exc:
                output = f"{exc.__class__.__name__}: {exc}"
            self.root.after(0, lambda: self._finish_background(output))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_background(self, output: str) -> None:
        self._busy = False
        # Stop progress animation
        self._progress.stop()
        self._stop_button.configure(state="disabled")
        if self._stop_triggered:
            self._stop_triggered = False
            self._write_command_output("Stopped by user.")
            self._update_action_buttons()
            return
        output = ui_commands.finalize_run_output(
            output,
            time.time() - self._busy_started_at,
            workspace=self._active_workspace_root,
        )
        self._write_command_output(output)
        self._preview_ready = ui_commands.is_preview_ready(output)
        self._update_action_buttons()
        self._maybe_ask_clarifications(output)

    def _maybe_ask_clarifications(self, output: str) -> None:
        """If the finished run stopped for clarification, collect answers and re-run.

        Runs in the Tk main thread (called from ``_finish_background``).  The
        answers are appended to the Evidence panel as ground truth and the same
        action is re-launched with ``assume_clarification=True`` so the run can
        proceed past the clarification gate.
        """
        if not self.clarify_var.get() or self._clarify_assume_once:
            return
        if self._last_background is None:
            return
        label, task, worker = self._last_background
        if label not in {"preview", "apply", "apply + exec"}:
            return
        questions = ui_commands.extract_clarifying_questions(output)
        if not questions:
            return
        qa_pairs = self._ask_clarifications(questions)
        if qa_pairs is None:
            return
        block = ui_commands.clarification_evidence_block(qa_pairs)
        if self._evidence():
            self.evidence_text.insert("end", "\n\n")
        self.evidence_text.insert("end", block)
        self.evidence_text.see("end")
        self._clarify_assume_once = True
        self._run_background(label, task, worker)

    def _ask_clarifications(self, questions: list[str]) -> list[tuple[str, str]] | None:
        """Modal dialog: one Entry per question; OK returns (question, answer) pairs."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Clarifying questions")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text="The plan needs clarification. Empty answers mean 'use a reasonable default'.",
            wraplength=520,
        ).pack(anchor="w", padx=10, pady=(10, 4))
        entries: list[tuple[str, ttk.Entry]] = []
        for question in questions:
            ttk.Label(dialog, text=question, wraplength=520).pack(anchor="w", padx=10, pady=(8, 2))
            entry = ttk.Entry(dialog, width=72)
            entry.pack(fill="x", padx=10)
            entries.append((question, entry))
        result: list[list[tuple[str, str]] | None] = [None]

        def on_ok() -> None:
            result[0] = [
                (question, entry.get().strip() or "use a reasonable default")
                for question, entry in entries
            ]
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=10, pady=10)
        ttk.Button(buttons, text="OK", command=on_ok).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        if entries:
            entries[0][1].focus_set()
        self.root.wait_window(dialog)
        return result[0]

    def _schedule_busy_heartbeat(self) -> None:
        if not self._busy:
            return
        heartbeat = ui_commands.heartbeat_message(time.time() - self._busy_started_at)
        if not self._busy_lines or self._busy_lines[-1] != heartbeat:
            self._busy_lines.append(heartbeat)
            self._append_command_output(heartbeat)
        self.root.after(3000, self._schedule_busy_heartbeat)

    def _initial_progress_message(self, label: str, task: str) -> str:
        return ui_runners.initial_progress_message(label, task, self._active_workspace_root)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def _assume_clarification(self) -> bool:
        """Whether the next run should bypass the clarification gate.

        True unless the "Ask clarifying questions" checkbox is on; the
        one-shot override re-enables it for the post-answers re-run.
        """
        return (not self.clarify_var.get()) or self._clarify_assume_once

    def _preview_worker(self, task: str) -> str:
        return ui_runners.preview_worker(
            task,
            self._active_workspace_root,
            self._evidence(),
            assume_clarification=self._assume_clarification(),
        )

    def _logs_latest_worker(self, _task: str) -> str:
        return ui_runners.logs_latest_worker(self._active_workspace_root)

    def _artifact_worker(self, task: str, *, extract: bool) -> str:
        return ui_runners.artifact_worker(task, self._active_workspace_root, extract=extract)

    def _cve_worker(self, task: str) -> str:
        return ui_runners.cve_worker(task, self._active_workspace_root)

    def _appsechub_worker(self, task: str) -> str:
        return ui_runners.appsechub_worker(task)

    def _open_workspace_folder(self) -> None:
        """Open the active workspace in Explorer so results are easy to find."""
        try:
            os.startfile(self._active_workspace_root)
        except OSError as exc:
            self._write_command_output(f"Could not open workspace folder: {exc}")

    def _run_worker(self, task: str, *, apply: bool, exec_: bool) -> str:
        return ui_runners.run_worker(
            task,
            self._active_workspace_root,
            self._evidence(),
            apply=apply,
            exec_=exec_,
            smoke=self.smoke_var.get(),
            assume_clarification=self._assume_clarification(),
        )

    # ------------------------------------------------------------------
    # Button state
    # ------------------------------------------------------------------

    def _update_action_buttons(self) -> None:
        apply_state, exec_state = ui_commands.action_button_states(
            busy=self._busy,
            decision=self._last_decision,
            preview_ready=self._preview_ready,
        )
        self.apply_button.configure(state=apply_state)
        self.exec_button.configure(state=exec_state)

    # ------------------------------------------------------------------
    # Text widget helpers  (logic lives in ui_helpers; wired here)
    # ------------------------------------------------------------------

    def _make_readonly_copyable(self, widget: tk.Text, copy_callback) -> None:
        ui_helpers.make_readonly_copyable(
            widget,
            copy_callback,
            copy_sel_fn=lambda: ui_helpers.copy_selection_or_all(
                widget, copy_callback, self._copy_text
            ),
            select_all_fn=lambda: ui_helpers.select_all_text(widget),
        )

    def _make_editable_copyable(self, widget: tk.Text) -> None:
        ui_helpers.make_editable_copyable(
            widget,
            select_all_fn=lambda: ui_helpers.select_all_text(widget),
        )

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def _copy_command_output(self) -> None:
        self._copy_text(self._command_output_cache)

    def _copy_intent_output(self) -> None:
        self._copy_text(self._intent_output_cache)

    def _copy_capability_detail(self) -> None:
        self._copy_text(ui_helpers.get_widget_text(self.capability_detail))

    def _copy_all_output(self) -> None:
        self._copy_text(
            ui_commands.combined_copy_text(self._intent_output_cache, self._command_output_cache)
        )

    def _paste_evidence(self) -> None:
        try:
            clipboard = self.root.clipboard_get()
        except tk.TclError:
            self._write_command_output("Clipboard is empty or unavailable.")
            return
        if self._evidence():
            self.evidence_text.insert("end", "\n\n")
        self.evidence_text.insert("end", clipboard)
        self.evidence_text.see("end")

    def _clear_evidence(self) -> None:
        self.evidence_text.delete("1.0", "end")

    def _prepare_workspace(
        self, task: str, decision: IntentDecision | None, *, create: bool
    ) -> None:
        plan = plan_workspace(
            project_mode=self.project_mode_var.get(),
            task=task,
            decision=decision,
            at_base=self._active_workspace_root == self._base_workspace_root,
            task_changed=self._active_workspace_task != task,
        )
        if plan.use_project:
            if create and plan.needs_new:
                self._active_workspace_root = create_project_workspace(
                    self._base_workspace_root, task
                )
                self._active_workspace_task = task
            if create:
                self.workspace_var.set(ui_commands.workspace_status(self._active_workspace_root))
        else:
            self._active_workspace_root = self._base_workspace_root
            self._active_workspace_task = ""
            self.workspace_var.set(ui_commands.workspace_status(self._active_workspace_root))


def run_command_center_ui(autoclose_ms: int | None = None) -> int:
    if tk is None:
        print(f"Tkinter is not available: {_TK_IMPORT_ERROR}", file=sys.stderr)
        return 1
    root = (
        tk.Tk()
    )  # pragma: no cover — mainloop teardown prevents a second Tk() in the same process
    _app = CommandCenterUI(root)  # pragma: no cover
    root.update_idletasks()  # pragma: no cover
    if autoclose_ms is not None:  # pragma: no cover
        root.after(autoclose_ms, root.destroy)  # pragma: no cover
    root.mainloop()  # pragma: no cover
    return 0  # pragma: no cover

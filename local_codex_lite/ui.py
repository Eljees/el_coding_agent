from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = exc  # type: Exception | None
else:
    _TK_IMPORT_ERROR = None

from .capabilities import capability_brief_lines, discover_capabilities
from .intent import (
    IntentDecision,
    decision_as_dict,
    extract_artifact_input_path,
    extract_artifact_output_path,
    recognize_intent,
)
from .project_workspace import create_project_workspace
from .skill_registry import discover_skills, skill_brief_lines
from .task_heuristics import (
    cve_min_severity_for_task,
    format_duration,
    plan_workspace,
    temporary_cwd,
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
        # Task history
        self._task_history: list[str] = []
        # workspace_var created before _build so status bar can reference it
        self.workspace_var = tk.StringVar(value=f"workspace: {self._base_workspace_root}")
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

        self._build_agent_tab(agent_frame)
        self._build_chat_tab(chat_frame)

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
        ttk.Label(workspace_row, textvariable=self.workspace_var).pack(side="right")

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
        # Show first line of each task as the label
        labels = [t.splitlines()[0][:120] if t else "" for t in self._task_history]
        self._history_combo["values"] = labels

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
        try:
            Path(path).write_text(content, encoding="utf-8")
        except Exception as exc:
            self._append_command_output(f"\nExport failed: {exc}")

    # ------------------------------------------------------------------
    # Status bar probe (background thread)
    # ------------------------------------------------------------------

    def _probe_status(self) -> None:
        import subprocess as _sp
        import urllib.request as _ur

        # CVE-bin-tool
        try:
            r = _sp.run(
                ["cve-bin-tool", "--version"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            ver = (r.stdout.strip() or r.stderr.strip()).split("\n")[0]
            cve_status = f"cve-bin-tool: {ver}" if ver else "cve-bin-tool: ok"
        except FileNotFoundError:
            cve_status = "cve-bin-tool: not found"
        except Exception:
            cve_status = "cve-bin-tool: error"
        self.root.after(0, lambda s=cve_status: self._status_cve_var.set(s))  # type: ignore[misc]

        # LLM endpoint
        base_url = "http://localhost:8015/v1"
        try:
            from .config import load_config

            cfg = load_config(self._base_workspace_root)
            base_url = cfg.llm.base_url
        except Exception:
            pass
        try:
            _ur.urlopen(base_url.rstrip("/") + "/models", timeout=4)
            llm_status = f"LLM: {base_url} ok"
        except Exception:
            llm_status = f"LLM: {base_url} (unreachable)"
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
        try:
            from .config import load_config
            from .llm_client import OpenAICompatibleClient

            cfg = load_config(self._active_workspace_root)
            client = OpenAICompatibleClient(cfg.llm)
            full_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful coding assistant embedded in a local agent tool. "
                        "Answer questions about the code, tasks, and evidence concisely and accurately. "
                        "Do not generate patches unless explicitly asked."
                    ),
                },
                *messages,
            ]
            response = client.chat(full_messages, max_tokens=1024)
            answer = response.text.strip()
        except Exception as exc:
            answer = f"[Error: {exc}]"
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
        combined = self._command_output_cache
        if combined:
            combined += "\n"
        combined += content
        self._write_command_output(combined)

    def _write_intent(self, decision: IntentDecision) -> None:
        self._last_decision = decision
        self.can_do_var.set(f"can do: {decision.can_do}")
        self.requires_apply_var.set(f"requires apply: {decision.requires_apply}")
        self.requires_exec_var.set(f"requires exec: {decision.requires_exec}")
        self.missing_inputs_var.set(
            f"missing inputs: {', '.join(decision.missing_inputs) if decision.missing_inputs else '-'}"
        )
        self.safe_action_var.set(f"safe next action: {decision.safe_next_action}")
        self._intent_output_cache = json.dumps(
            decision_as_dict(decision), ensure_ascii=False, indent=2
        )
        self._set_text(self.intent_text, self._intent_output_cache)
        self._update_action_buttons()

    def _show_capability_detail(self, *_args) -> None:
        index = self.capability_list.curselection()
        if not index:
            return
        self.tool_list.selection_clear(0, "end")
        self.skill_list.selection_clear(0, "end")
        capability = self.capabilities[index[0]]
        lines = [
            f"id: {capability.id}",
            f"title: {capability.title}",
            f"safety: {capability.safety_level}",
            f"requires_apply: {capability.requires_apply}",
            f"requires_exec: {capability.requires_exec}",
            "",
            "description:",
            capability.description,
            "",
            "examples:",
        ]
        lines.extend(f"- {item}" for item in capability.examples)
        lines.extend(["", "cli:", capability.cli_equivalent])
        self.capability_detail.configure(state="normal")
        self.capability_detail.delete("1.0", "end")
        self.capability_detail.insert("1.0", "\n".join(lines))
        self.capability_detail.configure(state="disabled")

    def _show_tool_detail(self, *_args) -> None:
        index = self.tool_list.curselection()
        if not index:
            return
        self.capability_list.selection_clear(0, "end")
        self.skill_list.selection_clear(0, "end")
        tool = self.tools[index[0]]
        lines = [
            f"name: {tool.name}",
            f"safety: {tool.safety_level}",
            f"requires_exec: {tool.requires_exec}",
            f"executor: {tool.executor}",
            "",
            "description:",
            tool.description,
            "",
            "schema:",
            json.dumps(tool.schema, ensure_ascii=False, indent=2),
        ]
        self.capability_detail.configure(state="normal")
        self.capability_detail.delete("1.0", "end")
        self.capability_detail.insert("1.0", "\n".join(lines))
        self.capability_detail.configure(state="disabled")

    def _show_skill_detail(self, *_args) -> None:
        index = self.skill_list.curselection()
        if not index or not self.skills:
            return
        self.capability_list.selection_clear(0, "end")
        self.tool_list.selection_clear(0, "end")
        skill = self.skills[index[0]]
        lines = [
            f"name: {skill.name}",
            f"path: {skill.path}",
            "",
            "summary:",
            skill.summary,
        ]
        self.capability_detail.configure(state="normal")
        self.capability_detail.delete("1.0", "end")
        self.capability_detail.insert("1.0", "\n".join(lines))
        self.capability_detail.configure(state="disabled")

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
        self._write_command_output(
            "Intent analysis completed in-process.\n\n"
            + json.dumps(decision_as_dict(decision), ensure_ascii=False, indent=2)
        )

    def preview(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._preview_ready = False
        decision = recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        self._save_task_to_history(task)
        if decision.intent == "evidence.artifacts.inspect":
            self._run_background(
                "artifacts inspect",
                task,
                lambda current_task: self._artifact_worker(current_task, extract=False),
            )
            return
        if decision.intent == "evidence.cve_scan":
            self._run_background("cve scan", task, self._cve_worker)
            return
        self._run_background("preview", task, self._preview_worker)

    def logs_latest(self) -> None:
        self._run_background("logs latest", "", self._logs_latest_worker)

    def apply_changes(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        decision = self._last_decision or recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        self._save_task_to_history(task)
        if decision.intent == "evidence.artifacts.inspect":
            self._run_background(
                "artifacts extract",
                task,
                lambda current_task: self._artifact_worker(current_task, extract=True),
            )
            return
        if decision.intent == "evidence.cve_scan":
            self._run_background("cve scan", task, self._cve_worker)
            return
        self._run_background(
            "apply",
            task,
            lambda current_task: self._run_worker(current_task, apply=True, exec_=False),
        )

    def exec_changes(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._save_task_to_history(task)
        self._run_background(
            "apply + exec",
            task,
            lambda current_task: self._run_worker(current_task, apply=True, exec_=True),
        )

    # ------------------------------------------------------------------
    # Background worker infrastructure
    # ------------------------------------------------------------------

    def _run_background(self, label: str, task: str, worker) -> None:
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
        if output:
            output = output.strip()
            output = (
                output + f"\n\ncompleted in {format_duration(time.time() - self._busy_started_at)}"
            )
        self._write_command_output(output)
        lower = output.lower()
        self._preview_ready = (
            "patch preview ok" in lower or "patch applied" in lower or "run completed" in lower
        )
        self._update_action_buttons()

    def _schedule_busy_heartbeat(self) -> None:
        if not self._busy:
            return
        elapsed = format_duration(time.time() - self._busy_started_at)
        heartbeat = f"still running: {elapsed}"
        if not self._busy_lines or self._busy_lines[-1] != heartbeat:
            self._busy_lines.append(heartbeat)
            self._append_command_output(heartbeat)
        self.root.after(3000, self._schedule_busy_heartbeat)

    def _initial_progress_message(self, label: str, task: str) -> str:
        lines = [f"Running {label}...", f"Workspace: {self._active_workspace_root}"]
        if label == "cve scan":
            input_root = extract_artifact_input_path(task)
            extract_to = extract_artifact_output_path(task)
            severity = cve_min_severity_for_task(task)
            lines.extend(
                [
                    "CVE scan started.",
                    f"input={input_root or '-'}",
                    f"min_severity={severity}",
                    f"extract_to={extract_to or 'default beside artifact'}",
                    "stage=resolve input",
                    "stage=unpack artifacts if needed",
                    "stage=run cve-bin-tool",
                    "stage=write evidence and reports",
                    "cve-bin-tool will run next; this can take several minutes.",
                ]
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def _preview_worker(self, task: str) -> str:
        from . import cli as cli_module

        buffer = io.StringIO()
        evidence_text = self._evidence()
        args = argparse.Namespace(
            task=task, evidence_file=[], evidence_stdin=bool(evidence_text), rag=False
        )
        with (
            temporary_cwd(self._active_workspace_root),
            contextlib.redirect_stdout(buffer),
            contextlib.redirect_stderr(buffer),
            self._redirect_optional_stdin(evidence_text),
        ):
            code = cli_module.cmd_preview(args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Preview finished with exit code {code}"

    def _logs_latest_worker(self, _task: str) -> str:
        from . import cli as cli_module

        buffer = io.StringIO()
        args = argparse.Namespace()
        with (
            temporary_cwd(self._active_workspace_root),
            contextlib.redirect_stdout(buffer),
            contextlib.redirect_stderr(buffer),
        ):
            code = cli_module.cmd_logs_latest(args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Logs latest finished with exit code {code}"

    def _artifact_worker(self, task: str, *, extract: bool) -> str:
        from . import cli as cli_module

        input_root = extract_artifact_input_path(task)
        if not input_root:
            return "Artifact input path not found in task."
        extract_to = extract_artifact_output_path(task)
        buffer = io.StringIO()
        args = argparse.Namespace(
            input_root=input_root,
            extract_to=extract_to or None,
            extract_to_flag=None,
            extract=extract,
            max_depth=2,
            max_files=2000,
            max_total_bytes=500_000_000,
        )
        with (
            temporary_cwd(self._active_workspace_root),
            contextlib.redirect_stdout(buffer),
            contextlib.redirect_stderr(buffer),
        ):
            code = cli_module.cmd_evidence_artifacts_inspect(args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Artifact inspection finished with exit code {code}"

    def _cve_worker(self, task: str) -> str:
        from . import cli as cli_module

        input_root = extract_artifact_input_path(task)
        if not input_root:
            return "CVE scan input path not found in task."
        extract_to = extract_artifact_output_path(task)
        severity = cve_min_severity_for_task(task)
        buffer = io.StringIO()
        args = argparse.Namespace(
            action_or_input=input_root,
            input_root=None,
            extract_to=extract_to or None,
            output_dir=None,
            install=False,
            update_db=False,
            skip_unpack=False,
            offline=False,
            min_severity=severity,
            format="json,md,high-critical-md",
        )
        with (
            temporary_cwd(self._active_workspace_root),
            contextlib.redirect_stdout(buffer),
            contextlib.redirect_stderr(buffer),
        ):
            code = cli_module.cmd_evidence_cve_scan(args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"CVE scan finished with exit code {code}"

    def _run_worker(self, task: str, *, apply: bool, exec_: bool) -> str:
        from . import cli as cli_module

        buffer = io.StringIO()
        evidence_text = self._evidence()
        args = argparse.Namespace(
            task=task,
            dry_run=False,
            apply=apply,
            exec=exec_,
            assume_clarification=True,
            evidence_file=[],
            evidence_stdin=bool(evidence_text),
        )
        with (
            temporary_cwd(self._active_workspace_root),
            contextlib.redirect_stdout(buffer),
            contextlib.redirect_stderr(buffer),
            self._redirect_optional_stdin(evidence_text),
        ):
            code = cli_module._run_task(task, args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Run finished with exit code {code}"

    # ------------------------------------------------------------------
    # Button state
    # ------------------------------------------------------------------

    def _update_action_buttons(self) -> None:
        apply_state = "disabled"
        exec_state = "disabled"
        if not self._busy and self._last_decision is not None:
            if (
                (
                    self._last_decision.intent == "evidence.artifacts.inspect"
                    and self._last_decision.can_do == "yes"
                )
                or (
                    self._last_decision.intent == "evidence.cve_scan"
                    and self._last_decision.can_do == "yes"
                )
                or (
                    self._preview_ready
                    and self._last_decision.intent in {"run.preview", "run.apply", "run.exec"}
                )
            ):
                apply_state = "normal"
            if self._preview_ready and (
                self._last_decision.intent == "run.exec" or self._last_decision.requires_exec
            ):
                exec_state = "normal"
        self.apply_button.configure(state=apply_state)
        self.exec_button.configure(state=exec_state)

    # ------------------------------------------------------------------
    # Text widget helpers
    # ------------------------------------------------------------------

    def _make_readonly_copyable(self, widget: tk.Text, copy_callback) -> None:
        widget.configure(state="disabled")
        widget.bind(
            "<Control-c>", lambda _event: self._copy_selection_or_all(widget, copy_callback)
        )
        widget.bind("<Control-a>", lambda _event: self._select_all(widget))
        widget.bind(
            "<Command-c>", lambda _event: self._copy_selection_or_all(widget, copy_callback)
        )
        widget.bind("<Command-a>", lambda _event: self._select_all(widget))
        widget.bind(
            "<Button-3>", lambda event: self._show_text_context_menu(widget, copy_callback, event)
        )

    def _make_editable_copyable(self, widget: tk.Text) -> None:
        widget.bind("<Control-a>", lambda _event: self._select_all(widget))
        widget.bind("<Command-a>", lambda _event: self._select_all(widget))
        widget.bind(
            "<Button-3>", lambda event: self._show_editable_text_context_menu(widget, event)
        )

    def _select_all(self, widget: tk.Text) -> str:
        prior_state = str(widget.cget("state"))
        if prior_state == "disabled":
            widget.configure(state="normal")
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "1.0")
        widget.see("1.0")
        if prior_state == "disabled":
            widget.configure(state="disabled")
        return "break"

    def _copy_selection_or_all(self, widget: tk.Text, copy_callback) -> str:
        try:
            selected = widget.get("sel.first", "sel.last")
        except tk.TclError:
            copy_callback()
            return "break"
        self._copy_text(selected)
        return "break"

    def _show_text_context_menu(self, widget: tk.Text, copy_callback, event) -> str:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(
            label="Copy selection",
            command=lambda: self._copy_selection_or_all(widget, copy_callback),
        )
        menu.add_command(label="Copy all", command=copy_callback)
        menu.add_command(label="Select all", command=lambda: self._select_all(widget))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _show_editable_text_context_menu(self, widget: tk.Text, event) -> str:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(
            label="Copy selection",
            command=lambda: self._copy_selection_or_all(
                widget, lambda: self._copy_widget_contents(widget)
            ),
        )
        menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_command(label="Select all", command=lambda: self._select_all(widget))
        menu.add_command(label="Clear", command=lambda: widget.delete("1.0", "end"))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def _copy_command_output(self) -> None:
        self._copy_text(self._command_output_cache)

    def _copy_intent_output(self) -> None:
        self._copy_text(self._intent_output_cache)

    def _copy_capability_detail(self) -> None:
        self._copy_widget_contents(self.capability_detail)

    def _copy_widget_contents(self, widget: tk.Text) -> None:
        prior_state = str(widget.cget("state"))
        if prior_state == "disabled":
            widget.configure(state="normal")
        text = widget.get("1.0", "end-1c")
        if prior_state == "disabled":
            widget.configure(state="disabled")
        self._copy_text(text)

    def _copy_all_output(self) -> None:
        combined = "\n\n".join(
            part
            for part in (
                "IntentDecision JSON:\n" + self._intent_output_cache
                if self._intent_output_cache
                else "",
                "Command output:\n" + self._command_output_cache
                if self._command_output_cache
                else "",
            )
            if part
        )
        self._copy_text(combined)

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

    @contextlib.contextmanager
    def _redirect_optional_stdin(self, evidence_text: str):
        if not evidence_text:
            yield
            return
        previous = sys.stdin
        sys.stdin = io.StringIO(evidence_text)
        try:
            yield
        finally:
            sys.stdin = previous

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
                self.workspace_var.set(f"workspace: {self._active_workspace_root}")
        else:
            self._active_workspace_root = self._base_workspace_root
            self._active_workspace_task = ""
            self.workspace_var.set(f"workspace: {self._active_workspace_root}")


def run_command_center_ui(autoclose_ms: int | None = None) -> int:
    if tk is None:
        print(f"Tkinter is not available: {_TK_IMPORT_ERROR}", file=sys.stderr)
        return 1
    root = tk.Tk()
    _app = CommandCenterUI(root)
    root.update_idletasks()
    if autoclose_ms is not None:
        root.after(autoclose_ms, root.destroy)
    root.mainloop()
    return 0

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception as exc:  # noqa: BLE001
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = exc
else:
    _TK_IMPORT_ERROR = None

from .capabilities import capability_brief_lines, default_capabilities
from .project_workspace import create_project_workspace, should_use_project_workspace
from .skill_registry import discover_skills, skill_brief_lines
from .tool_registry import default_tools, tool_brief_lines
from .intent import IntentDecision, decision_as_dict, extract_artifact_input_path, extract_artifact_output_path, recognize_intent


def should_create_project_workspace(task: str, decision: IntentDecision | None = None) -> bool:
    if decision is not None and decision.intent not in {"run.preview", "run.apply", "run.exec"}:
        return False
    return should_use_project_workspace(task)


@contextlib.contextmanager
def temporary_cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CommandCenterUI:
    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.capabilities = default_capabilities()
        self.tools = default_tools()
        self.skills = discover_skills(Path.cwd())
        self._command_output_cache = ""
        self._intent_output_cache = ""
        self._last_decision: IntentDecision | None = None
        self._preview_ready = False
        self._busy = False
        self._base_workspace_root = Path.cwd().resolve()
        self._active_workspace_root = self._base_workspace_root
        self._active_workspace_task = ""
        self._build()

    def _build(self) -> None:
        self.root.title("local-codex-lite command center")
        self.root.geometry("1120x760")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        top = ttk.Frame(main)
        top.pack(fill="x")
        left = ttk.Frame(top)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(top, width=320)
        right.pack(side="right", fill="y", padx=(12, 0))

        ttk.Label(left, text="Human task").pack(anchor="w")
        self.task_text = tk.Text(left, height=5, wrap="word")
        self.task_text.pack(fill="x", expand=False, pady=(4, 8))
        self._make_editable_copyable(self.task_text)

        evidence_frame = ttk.LabelFrame(left, text="Evidence / traceback")
        evidence_frame.pack(fill="x", expand=False, pady=(0, 8))
        self.evidence_text = tk.Text(evidence_frame, height=8, wrap="word")
        self.evidence_text.pack(fill="x", expand=False, padx=6, pady=(6, 6))
        self._make_editable_copyable(self.evidence_text)
        evidence_actions = ttk.Frame(evidence_frame)
        evidence_actions.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(evidence_actions, text="Paste clipboard", command=self._paste_evidence).pack(side="left")
        ttk.Button(evidence_actions, text="Clear evidence", command=self._clear_evidence).pack(side="left", padx=(6, 0))

        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Analyze", command=self.analyze).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Preview", command=self.preview).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Logs Latest", command=self.logs_latest).pack(side="left", padx=(0, 6))
        self.apply_button = ttk.Button(buttons, text="Apply", command=self.apply_changes, state="disabled")
        self.apply_button.pack(side="left", padx=(0, 6))
        self.exec_button = ttk.Button(buttons, text="Exec", command=self.exec_changes, state="disabled")
        self.exec_button.pack(side="left")

        workspace_row = ttk.Frame(left)
        workspace_row.pack(fill="x", pady=(0, 8))
        self.project_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            workspace_row,
            text="Create dated project folder for new project tasks",
            variable=self.project_mode_var,
        ).pack(side="left")
        self.workspace_var = tk.StringVar(value=f"workspace: {self._base_workspace_root}")
        ttk.Label(workspace_row, textvariable=self.workspace_var).pack(side="right")

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

        output_row = ttk.Frame(left)
        output_row.pack(fill="both", expand=True)
        intent_frame = ttk.LabelFrame(output_row, text="IntentDecision JSON")
        intent_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.intent_text = tk.Text(intent_frame, wrap="word")
        self.intent_text.pack(fill="both", expand=True)
        self._make_readonly_copyable(self.intent_text, self._copy_intent_output)
        command_frame = ttk.LabelFrame(output_row, text="Command output")
        command_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))
        self.command_text = tk.Text(command_frame, wrap="word")
        self.command_text.pack(fill="both", expand=True)
        self._make_readonly_copyable(self.command_text, self._copy_command_output)

        command_actions = ttk.Frame(command_frame)
        command_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(command_actions, text="Copy output", command=self._copy_command_output).pack(side="left")
        ttk.Button(command_actions, text="Copy all", command=self._copy_all_output).pack(side="left", padx=(6, 0))

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

        self.capability_detail = tk.Text(right, height=12, wrap="word")
        self.capability_detail.pack(fill="both", expand=False, pady=(8, 0))
        self._make_readonly_copyable(self.capability_detail, self._copy_capability_detail)
        self.capability_list.bind("<<ListboxSelect>>", self._show_capability_detail)
        self.tool_list.bind("<<ListboxSelect>>", self._show_tool_detail)
        self.skill_list.bind("<<ListboxSelect>>", self._show_skill_detail)
        if self.capability_list.size():
            self.capability_list.selection_set(0)
            self._show_capability_detail()

        self._write_command_output("Analyze a task to see the suggested intent and safe next action.")

    def _task(self) -> str:
        return self.task_text.get("1.0", "end").strip()

    def _evidence(self) -> str:
        return self.evidence_text.get("1.0", "end").strip()

    def _set_text(self, widget: "tk.Text", content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _write_command_output(self, content: str) -> None:
        self._command_output_cache = content
        self._set_text(self.command_text, content)

    def _write_intent(self, decision: IntentDecision) -> None:
        self._last_decision = decision
        self.can_do_var.set(f"can do: {decision.can_do}")
        self.requires_apply_var.set(f"requires apply: {decision.requires_apply}")
        self.requires_exec_var.set(f"requires exec: {decision.requires_exec}")
        self.missing_inputs_var.set(f"missing inputs: {', '.join(decision.missing_inputs) if decision.missing_inputs else '-'}")
        self.safe_action_var.set(f"safe next action: {decision.safe_next_action}")
        self._intent_output_cache = json.dumps(decision_as_dict(decision), ensure_ascii=False, indent=2)
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

    def analyze(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._preview_ready = False
        decision = recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        self._prepare_workspace(task, decision, create=False)
        self._write_command_output("Intent analysis completed in-process.\n\n" + json.dumps(decision_as_dict(decision), ensure_ascii=False, indent=2))

    def preview(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._preview_ready = False
        decision = recognize_intent(task, self.capabilities)
        self._write_intent(decision)
        if decision.intent == "evidence.artifacts.inspect":
            self._run_background("artifacts inspect", task, lambda current_task: self._artifact_worker(current_task, extract=False))
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
        if decision.intent == "evidence.artifacts.inspect":
            self._run_background("artifacts extract", task, lambda current_task: self._artifact_worker(current_task, extract=True))
            return
        self._run_background("apply", task, lambda current_task: self._run_worker(current_task, apply=True, exec_=False))

    def exec_changes(self) -> None:
        task = self._task()
        if not task:
            self._write_command_output("Enter a task first.")
            return
        self._run_background("apply + exec", task, lambda current_task: self._run_worker(current_task, apply=True, exec_=True))

    def _run_background(self, label: str, task: str, worker) -> None:
        if label in {"preview", "apply", "apply + exec"}:
            decision = self._last_decision or recognize_intent(task, self.capabilities)
            self._prepare_workspace(task, decision, create=True)
        self._busy = True
        self._update_action_buttons()
        self._write_command_output(f"Running {label}...\nWorkspace: {self._active_workspace_root}")

        def runner() -> None:
            try:
                output = worker(task)
            except Exception as exc:  # noqa: BLE001
                output = f"{exc.__class__.__name__}: {exc}"
            self.root.after(0, lambda: self._finish_background(output))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_background(self, output: str) -> None:
        self._busy = False
        self._write_command_output(output)
        lower = output.lower()
        # Rich strips markup when writing to a StringIO buffer, so check plain text.
        self._preview_ready = (
            "patch preview ok" in lower
            or "patch applied" in lower
            or "run completed" in lower
        )
        self._update_action_buttons()

    def _preview_worker(self, task: str) -> str:
        from . import cli as cli_module

        buffer = io.StringIO()
        evidence_text = self._evidence()
        args = argparse.Namespace(task=task, evidence_file=[], evidence_stdin=bool(evidence_text), rag=False)
        with temporary_cwd(self._active_workspace_root), contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer), self._redirect_optional_stdin(evidence_text):
            code = cli_module.cmd_preview(args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Preview finished with exit code {code}"

    def _logs_latest_worker(self, _task: str) -> str:
        from . import cli as cli_module

        buffer = io.StringIO()
        args = argparse.Namespace()
        with temporary_cwd(self._active_workspace_root), contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
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
        with temporary_cwd(self._active_workspace_root), contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = cli_module.cmd_evidence_artifacts_inspect(args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Artifact inspection finished with exit code {code}"

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
        with temporary_cwd(self._active_workspace_root), contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer), self._redirect_optional_stdin(evidence_text):
            code = cli_module._run_task(task, args)
        output = buffer.getvalue().strip()
        if output:
            return output + (f"\n\n(exit code: {code})" if code else "")
        return f"Run finished with exit code {code}"

    def _update_action_buttons(self) -> None:
        apply_state = "disabled"
        exec_state = "disabled"
        if not self._busy and self._last_decision is not None:
            if self._last_decision.intent == "evidence.artifacts.inspect" and self._last_decision.can_do == "yes":
                apply_state = "normal"
            elif self._preview_ready and self._last_decision.intent in {"run.preview", "run.apply", "run.exec"}:
                apply_state = "normal"
            if self._preview_ready and (self._last_decision.intent == "run.exec" or self._last_decision.requires_exec):
                exec_state = "normal"
        self.apply_button.configure(state=apply_state)
        self.exec_button.configure(state=exec_state)

    def _make_readonly_copyable(self, widget: "tk.Text", copy_callback) -> None:
        widget.configure(state="disabled")
        widget.bind("<Control-c>", lambda _event: self._copy_selection_or_all(widget, copy_callback))
        widget.bind("<Control-a>", lambda _event: self._select_all(widget))
        widget.bind("<Command-c>", lambda _event: self._copy_selection_or_all(widget, copy_callback))
        widget.bind("<Command-a>", lambda _event: self._select_all(widget))
        widget.bind("<Button-3>", lambda event: self._show_text_context_menu(widget, copy_callback, event))

    def _make_editable_copyable(self, widget: "tk.Text") -> None:
        widget.bind("<Control-a>", lambda _event: self._select_all(widget))
        widget.bind("<Command-a>", lambda _event: self._select_all(widget))
        widget.bind("<Button-3>", lambda event: self._show_editable_text_context_menu(widget, event))

    def _select_all(self, widget: "tk.Text") -> str:
        prior_state = str(widget.cget("state"))
        if prior_state == "disabled":
            widget.configure(state="normal")
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "1.0")
        widget.see("1.0")
        if prior_state == "disabled":
            widget.configure(state="disabled")
        return "break"

    def _copy_selection_or_all(self, widget: "tk.Text", copy_callback) -> str:
        try:
            selected = widget.get("sel.first", "sel.last")
        except tk.TclError:
            copy_callback()
            return "break"
        self._copy_text(selected)
        return "break"

    def _show_text_context_menu(self, widget: "tk.Text", copy_callback, event) -> str:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy selection", command=lambda: self._copy_selection_or_all(widget, copy_callback))
        menu.add_command(label="Copy all", command=copy_callback)
        menu.add_command(label="Select all", command=lambda: self._select_all(widget))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _show_editable_text_context_menu(self, widget: "tk.Text", event) -> str:
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy selection", command=lambda: self._copy_selection_or_all(widget, lambda: self._copy_widget_contents(widget)))
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

    def _copy_widget_contents(self, widget: "tk.Text") -> None:
        prior_state = str(widget.cget("state"))
        if prior_state == "disabled":
            widget.configure(state="normal")
        text = widget.get("1.0", "end-1c")
        if prior_state == "disabled":
            widget.configure(state="disabled")
        self._copy_text(text)

    def _copy_all_output(self) -> None:
        combined = "\n\n".join(
            part for part in (
                "IntentDecision JSON:\n" + self._intent_output_cache if self._intent_output_cache else "",
                "Command output:\n" + self._command_output_cache if self._command_output_cache else "",
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

    def _prepare_workspace(self, task: str, decision: IntentDecision | None, *, create: bool) -> None:
        if self.project_mode_var.get() and should_create_project_workspace(task, decision):
            if create and (self._active_workspace_task != task or self._active_workspace_root == self._base_workspace_root):
                self._active_workspace_root = create_project_workspace(self._base_workspace_root, task)
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
    if autoclose_ms is not None:
        root.after(autoclose_ms, root.destroy)
    root.mainloop()
    return 0

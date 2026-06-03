"""LLM-backed read commands: ``preview`` (plan+patch) and ``ask`` (Q&A).

Split out of ``cli.py``; re-exported from ``cli`` for backwards compatibility
and the test-suite, which monkeypatches these handlers' dependencies.
"""

from __future__ import annotations

import argparse

from .cli_utils import (
    console,
    workspace_root,
)
from .cli_utils import (
    load_evidence_block as _load_evidence_block,
)
from .cli_utils import (
    load_rag_context as _load_rag_context,
)
from .cli_utils import (
    merge_context_blocks as _merge_context_blocks,
)
from .cli_utils import (
    print_plan_summary as _print_plan_summary,
)
from .cli_utils import (
    print_retrieved_rag_context as _print_retrieved_rag_context,
)
from .cli_utils import (
    print_selected_files as _print_selected_files,
)
from .cli_utils import (
    selected_files as _selected_files,
)
from .config import UnknownProfileError, apply_profile, config_path, load_config
from .doctor import preview_patch
from .llm_client import OpenAICompatibleClient
from .patcher import detect_runtime_fix_context
from .planner import make_patch, make_plan
from .project_workspace import resolve_task_workspace
from .prompts import ask_prompt
from .rag import RagProviderError


def cmd_preview(args: argparse.Namespace) -> int:
    base_root = workspace_root()
    root = resolve_task_workspace(base_root, args.task)
    if root != base_root:
        console.print(f"Project workspace: {root}")
    cfg = load_config(root)
    try:
        cfg = apply_profile(cfg, getattr(args, "profile", None))
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    evidence_text = _load_evidence_block(args.evidence_file, use_stdin=args.evidence_stdin)
    runtime_fix = detect_runtime_fix_context(args.task, evidence_text, root)
    rag_context_text = (
        _load_rag_context(root, cfg, args.task) if getattr(args, "rag", False) else ""
    )
    selected = _selected_files(root, args.task, cfg)
    _print_selected_files(root, selected)
    if rag_context_text:
        _print_retrieved_rag_context(rag_context_text)
    try:
        plan = make_plan(
            args.task,
            root,
            cfg,
            extra_context=_merge_context_blocks(evidence_text, rag_context_text),
            runtime_fix=runtime_fix,
        )
        _print_plan_summary(plan)
        patch = make_patch(
            args.task,
            plan,
            root,
            cfg,
            extra_context=_merge_context_blocks(evidence_text, rag_context_text),
            runtime_fix=runtime_fix,
        )
        return preview_patch(root, patch)
    except RagProviderError as exc:
        console.print("[red]RAG unavailable[/red]")
        console.print(str(exc))
        return 1
    except Exception as exc:
        console.print("[red]Preview failed[/red]")
        console.print(f"{exc.__class__.__name__}: {exc}")
        return 1


def cmd_ask(question: str, args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    try:
        cfg = apply_profile(cfg, getattr(args, "profile", None))
    except UnknownProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    context = f"Workspace root: {root}\nConfig path: {config_path(root)}"
    evidence_text = _load_evidence_block(args.evidence_file, use_stdin=args.evidence_stdin)
    try:
        rag_context_text = (
            _load_rag_context(root, cfg, question) if getattr(args, "rag", False) else ""
        )
        client = OpenAICompatibleClient(cfg.llm)
        if rag_context_text:
            _print_retrieved_rag_context(rag_context_text)
        messages = ask_prompt(
            question, context, evidence=evidence_text, rag_context=rag_context_text
        )
        response = client.chat(messages, status_label="Answering question")
        console.print(response.text)
        return 0
    except RagProviderError as exc:
        console.print("[red]RAG unavailable[/red]")
        console.print(str(exc))
        return 1

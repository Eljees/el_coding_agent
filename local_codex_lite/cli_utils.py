"""Shared utilities used across CLI command modules."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .config import AgentConfig
from .logging_utils import append_jsonl
from .logging_utils import sanitize_log_text as _sanitize_log_text_impl
from .patch_errors import PatchErrorClassification
from .rag import RagProviderError, format_retrieved_context, retrieve_rag_context
from .rich_compat import make_console
from .workspace import RankedWorkspaceFile, summarize_ranked_files

console = make_console()


def workspace_root() -> Path:
    return Path.cwd().resolve()


def ensure_utf8_output() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def print_selected_files(root: Path, ranked: list[RankedWorkspaceFile]) -> None:
    if not ranked:
        return
    console.print("[bold]Selected context files[/bold]")
    for item in ranked:
        rel = item.path.relative_to(root).as_posix()
        reason = item.reasons[0] if item.reasons else "ranked by relevance"
        console.print(f"- {rel} — {reason}")


def print_plan_summary(plan: dict) -> None:
    summary = plan.get("summary")
    if summary:
        console.print(f"[bold]Plan summary:[/bold] {summary}")


def print_patch_error(error: PatchErrorClassification, repair_attempt: int) -> None:
    console.print(f"[yellow]Patch failed:[/yellow] {error.title}")
    console.print(f"Reason: {error.detail}")
    console.print(f"Next: {error.suggested_action}")
    console.print(f"Repair attempt: {repair_attempt}")


def log_patch_error(
    run_dir: Path,
    stage: str,
    repair_attempt: int,
    error: PatchErrorClassification,
    raw_error: str,
) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {
            "stage": stage,
            "status": "patch_error",
            "patch_error_code": error.code,
            "title": error.title,
            "detail": error.detail,
            "retryable": error.retryable,
            "suggested_action": error.suggested_action,
            "raw_error": sanitize_log_text(raw_error),
            "repair_attempt": repair_attempt,
        },
    )


def sanitize_log_text(value: str, limit: int = 600) -> str:
    """Backward-compatible alias for ``logging_utils.sanitize_log_text``.

    Kept here because tests and other modules import
    ``cli_utils.sanitize_log_text`` directly.
    """
    return _sanitize_log_text_impl(value, limit=limit)


def selected_files(root: Path, task: str, cfg: AgentConfig) -> list[RankedWorkspaceFile]:
    return summarize_ranked_files(
        root,
        task,
        cfg.workspace,
        allow_sensitive_read=cfg.safety.allow_sensitive_read,
        limit=5,
    )


def load_urls(repo_file: str | None, repo_urls: list[str] | None) -> list[str]:
    urls: list[str] = []
    if repo_file:
        for raw in Path(repo_file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    if repo_urls:
        urls.extend(repo_urls)
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def normalize_suggested_commands(payload: object) -> dict:
    """Normalize the LLM's suggested-commands payload defensively.

    Accepts the documented ``{"commands": [...]}`` envelope, a bare list (the
    model frequently returns one), or garbage -- anything unexpected collapses
    to ``{"commands": []}`` instead of crashing the apply path.
    """
    if isinstance(payload, list):
        commands: object = payload
    elif isinstance(payload, dict):
        commands = payload.get("commands")
    else:
        return {"commands": []}
    if not isinstance(commands, list):
        return {"commands": []}
    normalized: list[dict[str, str]] = []
    for item in commands:
        if isinstance(item, str):
            # Bare command string -> wrap into the canonical shape.
            item = {"cmd": item}
        if not isinstance(item, dict):
            continue
        cmd = str(item.get("cmd", "")).strip()
        if not looks_like_shell_command(cmd):
            continue
        normalized.append(
            {
                "cmd": cmd,
                "reason": str(item.get("reason", "")).strip(),
                "risk": str(item.get("risk", "")).strip(),
            }
        )
    return {"commands": normalized}


def looks_like_shell_command(cmd: str) -> bool:
    if not cmd:
        return False
    lower = cmd.lower()
    if lower.startswith(("create ", "implement ", "update ", "integrate ", "test ", "ensure ")):
        return False
    if lower.startswith(("sed ", "bash ", "chmod ", "notepad.exe", "code ")):
        return False
    if (
        re.search(r"[.!?]$", cmd)
        and " " in cmd
        and not any(
            marker in lower
            for marker in ("python", "pytest", "git", "pwsh", ".py", ".ps1", ".bat", "\\", "/")
        )
    ):
        return False
    return True


def load_evidence_block(raw_paths: list[str], *, use_stdin: bool = False) -> str:
    if not raw_paths:
        if not use_stdin:
            return ""
        return read_stdin_evidence()
    sections: list[str] = []
    stdin_text: str | None = None
    for raw_path in raw_paths:
        if raw_path in {"-", "stdin", "/dev/stdin"}:
            if use_stdin:
                if stdin_text is None:
                    stdin_text = read_stdin_evidence()
                sections.append(stdin_text)
            continue
        path = Path(raw_path)
        if not path.exists():
            raise SystemExit(f"Evidence file not found: {path}")
        if path.is_dir():
            candidates = sorted(p for p in path.rglob("*") if p.is_file())
        else:
            candidates = [path]
        for item in candidates:
            sections.append(render_evidence_item(item))
    return "\n\n".join(sections)


def load_rag_context(root: Path, cfg: AgentConfig, query: str) -> str:
    try:
        retrieved = retrieve_rag_context(query, root, cfg)
    except RagProviderError:
        return ""
    if not retrieved:
        return ""
    return format_retrieved_context(retrieved, cfg.rag.max_context_chars)


def print_retrieved_rag_context(context_text: str) -> None:
    if context_text:
        console.print("[bold]Retrieved RAG context[/bold]")
        console.print(context_text)


def merge_context_blocks(*blocks: str) -> str:
    return "\n\n".join(b for b in blocks if b)


def render_evidence_item(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.strip():
        return ""
    return f"=== {path.name} ===\n{text}"


def read_stdin_evidence() -> str:
    if sys.stdin.isatty():
        raise SystemExit("No stdin available for evidence input.")
    text = sys.stdin.read()
    if not text:
        raise SystemExit("No piped evidence received on stdin.")
    if not text.strip():
        raise SystemExit("Empty evidence received on stdin.")
    return text

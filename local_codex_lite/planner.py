from __future__ import annotations

import difflib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .config import AgentConfig
from .llm_client import (
    OpenAICompatibleClient,
    SupportsChat,
    extract_diff,
    extract_json,
    repair_json_response,
)
from .logging_utils import append_jsonl, sanitize_log_text
from .patcher import RuntimeFixContext
from .prompts import (
    assumption_prompt,
    command_prompt,
    evidence_context_block,
    patch_prompt,
    patch_repair_prompt_for_issue,
    plan_prompt,
    review_prompt,
    runtime_fix_single_file_command_prompt,
    runtime_fix_single_file_patch_prompt,
    runtime_fix_single_file_plan_prompt,
)
from .retrying import RetryIssue, classify_httpx_exception, strategy_for_issue
from .targeting import TaskTarget, detect_task_target
from .workspace import compact_context

T = TypeVar("T")


@dataclass(frozen=True)
class PlanResult:
    plan: dict
    diff: str
    commands: dict
    context: str


@dataclass(frozen=True)
class ReviewResult:
    review: dict
    context: str


@dataclass(frozen=True)
class RepairDiagnosis:
    intended_target: TaskTarget | None
    touched_paths: tuple[str, ...]
    drifted: bool


def make_plan(
    task: str,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None = None,
    extra_context: str = "",
    runtime_fix: RuntimeFixContext | None = None,
    *,
    client: SupportsChat | None = None,
) -> dict:
    client = client if client is not None else OpenAICompatibleClient(config.llm)
    if runtime_fix is not None:
        messages = runtime_fix_single_file_plan_prompt(
            task,
            runtime_fix.target_path.relative_to(workspace_root).as_posix(),
            runtime_fix.traceback_text,
            runtime_fix.current_text,
            related_files=tuple(
                (p.relative_to(workspace_root).as_posix(), text)
                for p, text in runtime_fix.secondary_files
            ),
        )
        budget = _budget_for_messages(messages, config.llm.max_tokens)
        response = client.chat(messages, max_tokens=budget, status_label="Planning")
        result = extract_json(response.text)
        _log_llm_attempt(
            run_dir,
            "plan",
            1,
            "success",
            issue_type="runtime_fix_single_file",
            strategy="focused_single_file",
            max_tokens=budget,
            context_chars=len(runtime_fix.current_text) + len(runtime_fix.traceback_text),
            response_text=response.text,
        )
        return result
    return _retry_with_context_variants(
        client=client,
        task=task,
        workspace_root=workspace_root,
        config=config,
        variant="plan",
        run_dir=run_dir,
        stage="plan",
        status_prefix="Planning",
        parse_response=extract_json,
        repair_response=lambda response_text, messages, budget: repair_json_response(
            client,
            messages,
            response_text,
            max_tokens=min(512, budget),
        ),
        prompt_builder=lambda context: plan_prompt(task, _merge_context(context, extra_context)),
    )


def make_patch(
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None = None,
    extra_context: str = "",
    runtime_fix: RuntimeFixContext | None = None,
    *,
    client: SupportsChat | None = None,
) -> str:
    client = client if client is not None else OpenAICompatibleClient(config.llm)
    if runtime_fix is not None:
        return _make_runtime_fix_patch(
            client, task, plan, workspace_root, config, run_dir, runtime_fix
        )
    return _make_standard_patch(client, task, plan, workspace_root, config, run_dir, extra_context)


def _make_runtime_fix_patch(
    client: SupportsChat,
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None,
    runtime_fix: RuntimeFixContext,
) -> str:
    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
    target_path = runtime_fix.target_path.relative_to(workspace_root).as_posix()
    context_chars = len(runtime_fix.current_text) + len(runtime_fix.traceback_text)
    last_error: str | None = None
    last_response_text: str = ""
    for attempt in range(1, 4):
        if attempt == 1:
            messages = runtime_fix_single_file_patch_prompt(
                task,
                plan_json,
                target_path,
                runtime_fix.traceback_text,
                runtime_fix.current_text,
                related_files=tuple(
                    (p.relative_to(workspace_root).as_posix(), text)
                    for p, text in runtime_fix.secondary_files
                ),
            )
            status_label = "Generating patch"
        else:
            messages = patch_repair_prompt_for_issue(
                "malformed_diff",
                task,
                plan_json,
                last_response_text,
                last_error or "runtime-fix patch response was not a valid unified diff",
                _runtime_fix_context_block(runtime_fix, workspace_root),
                repair_attempt=attempt - 1,
            )
            status_label = f"Repairing patch (attempt {attempt - 1}.runtime-fix)"
        budget = _budget_for_messages(messages, config.llm.max_tokens)
        try:
            timeout_override = None if attempt == 1 else min(45.0, float(config.llm.timeout))
            response = _chat_with_timeout(
                client,
                messages,
                max_tokens=budget,
                status_label=status_label,
                timeout=timeout_override,
            )
            last_response_text = response.text
            patch = extract_diff(response.text)
            _log_llm_attempt(
                run_dir,
                "patch",
                attempt,
                "success",
                issue_type="runtime_fix_single_file",
                strategy="focused_single_file",
                max_tokens=budget,
                context_chars=context_chars,
                response_text=patch,
            )
            return patch
        except ValueError as exc:
            last_error = str(exc)
            _log_llm_attempt(
                run_dir,
                "patch",
                attempt,
                "parse_error",
                issue_type="malformed_diff",
                strategy="focused_single_file",
                error=last_error,
                max_tokens=budget,
                context_chars=context_chars,
                response_text=last_response_text,
            )
        except Exception as exc:
            last_error = _format_exception(exc)
            _log_llm_attempt(
                run_dir,
                "patch",
                attempt,
                "request_error",
                issue_type=classify_httpx_exception(exc),
                strategy="focused_single_file",
                error=last_error,
                max_tokens=budget,
                context_chars=context_chars,
                response_text=_response_text_from_exception(exc),
            )
    replacement_patch = _repair_via_full_file_rewrite(
        client,
        task,
        plan,
        workspace_root,
        config,
        previous_patch=last_response_text,
        error=last_error or "runtime-fix patch generation returned malformed diff",
        issue_type="malformed_diff",
        repair_attempt=3,
        runtime_fix=runtime_fix,
    )
    if replacement_patch is not None:
        _log_llm_attempt(
            run_dir,
            "patch",
            4,
            "success",
            issue_type="runtime_fix_single_file",
            strategy="full_file_rewrite",
            max_tokens=min(2048, config.llm.max_tokens),
            context_chars=context_chars,
            response_text=replacement_patch,
        )
        return replacement_patch
    raise RuntimeError(
        f"patch generation failed after runtime-fix retries: {last_error or 'unknown error'}"
    ) from None


def _make_standard_patch(
    client: SupportsChat,
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None,
    extra_context: str,
) -> str:
    last_error: str | None = None
    last_issue: RetryIssue = "unknown"
    for attempt, context in enumerate(
        _context_variants(
            workspace_root, task, config, variant="patch", extra_context=extra_context
        ),
        start=1,
    ):
        messages = patch_prompt(task, json.dumps(plan, ensure_ascii=False, indent=2), context)
        budget = _budget_for_messages(messages, config.llm.max_tokens)
        try:
            response = client.chat(
                messages,
                max_tokens=budget,
                status_label=f"Generating patch (attempt {attempt})",
            )
            try:
                patch = extract_diff(response.text)
                _log_llm_attempt(
                    run_dir,
                    "patch",
                    attempt,
                    "success",
                    issue_type="unknown",
                    strategy="none",
                    max_tokens=budget,
                    context_chars=len(context),
                    response_text=patch,
                )
                return patch
            except ValueError as exc:
                last_error = str(exc)
                last_issue = "malformed_diff"
                _log_llm_attempt(
                    run_dir,
                    "patch",
                    attempt,
                    "parse_error",
                    issue_type=last_issue,
                    strategy=strategy_for_issue(last_issue),
                    error=last_error,
                    max_tokens=budget,
                    context_chars=len(context),
                    response_text=response.text,
                )
        except Exception as exc:
            last_error = _format_exception(exc)
            last_issue = classify_httpx_exception(exc)
            _log_llm_attempt(
                run_dir,
                "patch",
                attempt,
                "request_error",
                issue_type=last_issue,
                strategy=strategy_for_issue(last_issue),
                error=last_error,
                max_tokens=budget,
                context_chars=len(context),
                response_text=_response_text_from_exception(exc),
            )
        if last_issue == "context_too_large":
            continue
        if attempt < 3:
            time.sleep(0.5 * attempt)
            continue
        if last_error:
            raise RuntimeError(f"patch generation failed after retries: {last_error}") from None
    raise RuntimeError("patch generation failed")


def repair_patch_with_error(
    task: str,
    plan: dict,
    previous_patch: str,
    error: str,
    issue_type: str,
    workspace_root: Path,
    config: AgentConfig,
    extra_context: str = "",
    *,
    repair_attempt: int = 1,
    runtime_fix: RuntimeFixContext | None = None,
    client: SupportsChat | None = None,
) -> str:
    client = client if client is not None else OpenAICompatibleClient(config.llm)
    last_error: str | None = None
    diagnosis = _build_repair_diagnosis(task, workspace_root, previous_patch, error)
    effective_issue_type = "target_drift" if diagnosis.drifted else issue_type
    if diagnosis.intended_target is not None:
        replacement_patch = _repair_via_intended_target(
            client,
            task,
            plan,
            workspace_root,
            config,
            previous_patch=previous_patch,
            error=error,
            issue_type=effective_issue_type,
            repair_attempt=repair_attempt,
            diagnosis=diagnosis,
        )
        if replacement_patch is not None and replacement_patch.strip() != previous_patch.strip():
            return replacement_patch
    if issue_type in {"context_mismatch", "empty_patch"}:
        replacement_patch = _repair_via_full_file_rewrite(
            client,
            task,
            plan,
            workspace_root,
            config,
            previous_patch=previous_patch,
            error=error,
            issue_type=issue_type,
            repair_attempt=repair_attempt,
            runtime_fix=runtime_fix,
        )
        if replacement_patch is not None and replacement_patch.strip() != previous_patch.strip():
            return replacement_patch
    for variant_index, context in enumerate(
        _repair_context_variants(
            workspace_root,
            task,
            config,
            previous_patch=previous_patch,
            error=error,
            extra_context=extra_context,
            diagnosis=diagnosis,
        ),
        start=1,
    ):
        messages = patch_repair_prompt_for_issue(
            effective_issue_type,
            task,
            json.dumps(plan, ensure_ascii=False, indent=2),
            previous_patch,
            error,
            context,
            repair_attempt=repair_attempt,
        )
        try:
            response = client.chat(
                messages,
                max_tokens=min(1024, _budget_for_context(context, config.llm.max_tokens)),
                status_label=f"Repairing patch (attempt {repair_attempt}.{variant_index})",
            )
            patch = extract_diff(response.text)
        except Exception as exc:
            last_error = _format_exception(exc)
            continue
        if patch.strip() == previous_patch.strip():
            last_error = "repair returned the same patch as the failed attempt"
            continue
        return patch
    fallback_context = _merge_context(
        _build_repair_fallback_context(
            workspace_root,
            task,
            config,
            previous_patch=previous_patch,
            error=error,
            diagnosis=diagnosis,
        ),
        extra_context,
    )
    fallback_messages = patch_prompt(
        f"{task}\n\nRepair constraints:\n- The previous patch failed with issue type `{issue_type}`.\n"
        f"- The previous patch was rejected with: {error}\n"
        "- Do not repeat the same diff shape.\n"
        "- Do not make comment-only or whitespace-only changes.\n"
        "- Update the current file contents directly.",
        json.dumps(plan, ensure_ascii=False, indent=2),
        fallback_context,
    )
    try:
        fallback_response = client.chat(
            fallback_messages,
            max_tokens=min(1024, _budget_for_context(fallback_context, config.llm.max_tokens)),
            status_label=f"Regenerating patch (attempt {repair_attempt}.fallback)",
        )
        fallback_patch = extract_diff(fallback_response.text)
        if fallback_patch.strip() != previous_patch.strip():
            return fallback_patch
    except Exception as exc:
        last_error = _format_exception(exc)
    raise RuntimeError(last_error or "patch repair failed")


def suggest_commands(
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None = None,
    extra_context: str = "",
    runtime_fix: RuntimeFixContext | None = None,
    *,
    client: SupportsChat | None = None,
) -> dict:
    client = client if client is not None else OpenAICompatibleClient(config.llm)
    if runtime_fix is not None:
        messages = runtime_fix_single_file_command_prompt(
            task,
            json.dumps(plan, ensure_ascii=False, indent=2),
            runtime_fix.target_path.relative_to(workspace_root).as_posix(),
        )
        budget = _budget_for_messages(messages, config.llm.max_tokens)
        response = client.chat(messages, max_tokens=budget, status_label="Suggesting commands")
        result = extract_json(response.text)
        _log_llm_attempt(
            run_dir,
            "commands",
            1,
            "success",
            issue_type="runtime_fix_single_file",
            strategy="focused_single_file",
            max_tokens=budget,
            context_chars=len(runtime_fix.current_text) + len(runtime_fix.traceback_text),
            response_text=response.text,
        )
        return result
    return _retry_with_context_variants(
        client=client,
        task=task,
        workspace_root=workspace_root,
        config=config,
        variant="commands",
        run_dir=run_dir,
        stage="commands",
        status_prefix="Suggesting commands",
        parse_response=extract_json,
        repair_response=lambda response_text, messages, budget: repair_json_response(
            client,
            messages,
            response_text,
            max_tokens=min(256, budget),
        ),
        prompt_builder=lambda context: command_prompt(
            task,
            json.dumps(plan, ensure_ascii=False, indent=2),
            _merge_context(context, extra_context),
        ),
    )


def make_review(
    task: str,
    diff_text: str,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None = None,
    extra_context: str = "",
    *,
    client: SupportsChat | None = None,
) -> dict:
    client = client if client is not None else OpenAICompatibleClient(config.llm)
    review_context = _merge_context(
        compact_context(
            workspace_root,
            task,
            config.workspace,
            allow_sensitive_read=config.safety.allow_sensitive_read,
        ),
        extra_context,
    )
    messages = review_prompt(diff_text, review_context)
    budget = _budget_for_messages(messages, config.llm.max_tokens)
    response = client.chat(messages, max_tokens=budget, status_label="Reviewing code changes")
    try:
        result = extract_json(response.text)
        _log_llm_attempt(
            run_dir,
            "review",
            1,
            "success",
            issue_type="unknown",
            strategy="none",
            max_tokens=budget,
            context_chars=len(review_context) + len(diff_text),
            response_text=response.text,
        )
        return result
    except ValueError as exc:
        repaired = repair_json_response(
            client, messages, response.text, max_tokens=min(768, budget)
        )
        _log_llm_attempt(
            run_dir,
            "review",
            1,
            "parse_error",
            issue_type="malformed_json",
            strategy="none",
            error=str(exc),
            max_tokens=budget,
            context_chars=len(review_context) + len(diff_text),
            response_text=response.text,
        )
        return repaired


def revise_plan_with_assumptions(
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    run_dir: Path | None = None,
    extra_context: str = "",
    *,
    client: SupportsChat | None = None,
) -> dict:
    context = _merge_context(
        compact_context(
            workspace_root,
            task,
            config.workspace,
            allow_sensitive_read=config.safety.allow_sensitive_read,
        ),
        extra_context,
    )
    client = client if client is not None else OpenAICompatibleClient(config.llm)
    questions = (
        plan.get("clarifying_questions")
        if isinstance(plan.get("clarifying_questions"), list)
        else []
    )
    messages = assumption_prompt(
        task, json.dumps(plan, ensure_ascii=False, indent=2), context, [str(q) for q in questions]
    )
    budget = _budget_for_messages(messages, config.llm.max_tokens)
    response = client.chat(messages, max_tokens=min(768, budget), status_label="Revising plan")
    try:
        return extract_json(response.text)
    except ValueError:
        return repair_json_response(client, messages, response.text, max_tokens=min(512, budget))


def _budget_for_context(context: str, configured_max_tokens: int) -> int:
    estimated_input_tokens = max(1, len(context) // 4)
    safe_budget = max(128, 6000 - estimated_input_tokens - 512)
    return max(128, min(configured_max_tokens, safe_budget))


def _budget_for_messages(messages: list[dict[str, str]], configured_max_tokens: int) -> int:
    estimated_chars = sum(len(message.get("content", "")) for message in messages)
    estimated_input_tokens = max(1, estimated_chars // 4)
    safe_budget = max(128, 6000 - estimated_input_tokens - 512)
    return max(128, min(configured_max_tokens, safe_budget))


def _context_variants(
    workspace_root: Path,
    task: str,
    config: AgentConfig,
    variant: str,
    extra_context: str = "",
) -> list[str]:
    allow_sensitive = config.safety.allow_sensitive_read
    if variant == "plan":
        sizes = [(80, 6000), (50, 4000), (25, 2500)]
    elif variant == "patch":
        sizes = [(80, 6000), (45, 3500), (20, 2000)]
    else:
        sizes = [(80, 6000), (60, 4500), (30, 2500)]
    contexts = [
        compact_context(
            workspace_root,
            task,
            config.workspace,
            allow_sensitive_read=allow_sensitive,
            max_tree_entries=tree_limit,
            max_excerpt_chars=excerpt_limit,
        )
        for tree_limit, excerpt_limit in sizes
    ]
    return [_merge_context(context, extra_context) for context in contexts]


def _merge_context(base_context: str, extra_context: str) -> str:
    extra_context = extra_context.strip()
    if not extra_context:
        return base_context
    return f"{base_context}\n\n{evidence_context_block(extra_context)}"


def _build_repair_diagnosis(
    task: str,
    workspace_root: Path,
    previous_patch: str,
    error: str,
) -> RepairDiagnosis:
    intended_target = detect_task_target(task, workspace_root)
    touched_paths = tuple(_extract_failed_paths(previous_patch, error))
    if intended_target is None:
        return RepairDiagnosis(intended_target=None, touched_paths=touched_paths, drifted=False)
    drifted = bool(touched_paths) and not any(
        _path_matches_target(path, intended_target) for path in touched_paths
    )
    return RepairDiagnosis(
        intended_target=intended_target, touched_paths=touched_paths, drifted=drifted
    )


def _path_matches_target(path: str, target: TaskTarget) -> bool:
    candidate = path.replace("\\", "/").lower()
    target_path = target.path.lower()
    return candidate == target_path or Path(candidate).name == Path(target_path).name


def _build_intended_target_context(
    workspace_root: Path,
    diagnosis: RepairDiagnosis | None,
) -> str:
    if diagnosis is None or diagnosis.intended_target is None:
        return ""
    target = diagnosis.intended_target
    path = (workspace_root / target.path).resolve()
    lines = [
        "# Intended repair target",
        f"Target path: {target.path}",
        f"Target mode: {target.mode}",
        f"Target exists: {target.exists}",
    ]
    if diagnosis.touched_paths:
        lines.extend(
            ["", "Previous patch touched:", *[f"- {item}" for item in diagnosis.touched_paths]]
        )
    if path.is_file():
        content = path.read_text(encoding="utf-8", errors="replace")
        lines.extend(["", f"## Current file: {target.path}", content[:3000]])
    else:
        lines.extend(
            [
                "",
                "## Current file state",
                "The target file does not exist yet. Create only this file unless the task explicitly requires a test file.",
            ]
        )
    return "\n".join(lines)


def _repair_context_variants(
    workspace_root: Path,
    task: str,
    config: AgentConfig,
    *,
    previous_patch: str,
    error: str,
    extra_context: str = "",
    diagnosis: RepairDiagnosis | None = None,
) -> list[str]:
    target_context = _build_intended_target_context(workspace_root, diagnosis)
    targeted_context = target_context or _build_failed_file_context(
        workspace_root,
        previous_patch=previous_patch,
        error=error,
        max_chars_per_file=min(config.workspace.max_file_bytes, 2500),
    )
    minimal_context = "# Focused repair context\n" + (
        targeted_context or "No target files were extracted."
    )
    base_context = compact_context(
        workspace_root,
        task,
        config.workspace,
        allow_sensitive_read=config.safety.allow_sensitive_read,
        max_tree_entries=35,
        max_excerpt_chars=2500,
    )
    variants = [_merge_context(minimal_context, extra_context)]
    if targeted_context:
        variants.append(_merge_context(f"{base_context}\n\n{targeted_context}", extra_context))
    variants.append(_merge_context(base_context, extra_context))
    return variants


def _build_failed_file_context(
    workspace_root: Path,
    *,
    previous_patch: str,
    error: str,
    max_chars_per_file: int,
) -> str:
    paths = _extract_failed_paths(previous_patch, error)
    sections: list[str] = []
    for rel_path in paths[:4]:
        path = (workspace_root / rel_path).resolve()
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sections.append(f"## Current file: {rel_path}\n{content[:max_chars_per_file]}")
    if not sections:
        return ""
    return "# Failed patch target files\n" + "\n\n".join(sections)


def _build_repair_fallback_context(
    workspace_root: Path,
    task: str,
    config: AgentConfig,
    *,
    previous_patch: str,
    error: str,
    diagnosis: RepairDiagnosis | None = None,
) -> str:
    target_context = _build_intended_target_context(workspace_root, diagnosis)
    targeted_context = target_context or _build_failed_file_context(
        workspace_root,
        previous_patch=previous_patch,
        error=error,
        max_chars_per_file=min(config.workspace.max_file_bytes, 3000),
    )
    if targeted_context:
        return "# Focused regeneration context\n" + targeted_context
    return compact_context(
        workspace_root,
        task,
        config.workspace,
        allow_sensitive_read=config.safety.allow_sensitive_read,
        max_tree_entries=25,
        max_excerpt_chars=2000,
    )


def _runtime_fix_context_block(runtime_fix: RuntimeFixContext, workspace_root: Path) -> str:
    rel_path = runtime_fix.target_path.relative_to(workspace_root).as_posix()
    related = ""
    if runtime_fix.secondary_files:
        related_parts = ["", "Related files (read-only context; do NOT patch):"]
        for p, text in runtime_fix.secondary_files:
            try:
                p_rel = p.relative_to(workspace_root).as_posix()
            except ValueError:
                p_rel = str(p)
            snippet = text if len(text) <= 2000 else text[:2000] + "\n... (truncated)"
            related_parts.append(f"--- {p_rel} ---\n{snippet}")
        related = "\n".join(related_parts)
    return (
        "# Single-file runtime repair context\n"
        f"Target file: {rel_path}\n\n"
        f"Traceback:\n{runtime_fix.traceback_text}\n\n"
        f"Current file content:\n{runtime_fix.current_text}" + (related and ("\n" + related))
    )


def _repair_via_full_file_rewrite(
    client: OpenAICompatibleClient,
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    *,
    previous_patch: str,
    error: str,
    issue_type: str,
    repair_attempt: int,
    runtime_fix: RuntimeFixContext | None = None,
) -> str | None:
    if runtime_fix is not None:
        path = runtime_fix.target_path
        rel_path = runtime_fix.target_path.relative_to(workspace_root).as_posix()
        current_text = runtime_fix.current_text
    else:
        paths = _extract_failed_paths(previous_patch, error)
        if len(paths) != 1:
            return None
        rel_path = paths[0]
        path = (workspace_root / rel_path).resolve()
        if not path.is_file():
            return None
        current_text = path.read_text(encoding="utf-8", errors="replace")
    messages = [
        {
            "role": "system",
            "content": (
                "You repair a single file for a local coding agent.\n"
                "Return only the complete replacement file content.\n"
                "Do not return a unified diff.\n"
                "Do not include markdown fences or explanations.\n"
                "The provided current file content is authoritative.\n"
                "Do not rewrite imaginary lines that are not present in the current file content.\n"
                "Preserve existing logic unless the failure requires a direct change.\n"
                "Do not replace working code with placeholders, stubs, or pass statements.\n"
                "Return valid runnable source code for the full file.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task:\n{task}\n\n"
                f"Issue type: {issue_type}\n"
                f"Repair attempt: {repair_attempt}\n\n"
                f"Plan:\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n\n"
                f"Target file path:\n{rel_path}\n\n"
                f"Current file content:\n{current_text}\n\n"
                f"Failure details:\n{error}\n\n"
                "Return only the full corrected file content."
            ),
        },
    ]
    response = _chat_with_timeout(
        client,
        messages,
        max_tokens=min(2048, config.llm.max_tokens),
        status_label=f"Rewriting file (attempt {repair_attempt}.rewrite)",
        timeout=min(60.0, float(config.llm.timeout)),
    )
    replacement_text = _strip_fences(response.text)
    if not replacement_text.strip() or replacement_text.strip() == current_text.strip():
        return None
    return _build_unified_diff(rel_path, current_text, replacement_text)


def _repair_via_intended_target(
    client: OpenAICompatibleClient,
    task: str,
    plan: dict,
    workspace_root: Path,
    config: AgentConfig,
    *,
    previous_patch: str,
    error: str,
    issue_type: str,
    repair_attempt: int,
    diagnosis: RepairDiagnosis,
) -> str | None:
    target = diagnosis.intended_target
    if target is None:
        return None
    path = (workspace_root / target.path).resolve()
    target_context = _build_intended_target_context(workspace_root, diagnosis)
    messages = patch_repair_prompt_for_issue(
        issue_type,
        task,
        json.dumps(plan, ensure_ascii=False, indent=2),
        previous_patch,
        error,
        target_context,
        repair_attempt=repair_attempt,
    )
    response = _chat_with_timeout(
        client,
        messages,
        max_tokens=min(1024, config.llm.max_tokens),
        status_label=f"Retargeting patch (attempt {repair_attempt}.target)",
        timeout=min(60.0, float(config.llm.timeout)),
    )
    patch = extract_diff(response.text)
    patch_paths = _extract_failed_paths(patch, "")
    if patch_paths and not any(_path_matches_target(item, target) for item in patch_paths):
        return None
    if not target.exists and path.exists():
        return None
    return patch


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip("\n")
    return text


def _build_unified_diff(rel_path: str, before: str, after: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="\n",
    )
    return "".join(diff)


def _chat_with_timeout(
    client: OpenAICompatibleClient,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    status_label: str,
    timeout: float | None,
):
    client_config = getattr(client, "config", None)
    if timeout is None or client_config is None or not hasattr(client_config, "timeout"):
        return client.chat(messages, max_tokens=max_tokens, status_label=status_label)
    original_timeout = client_config.timeout
    client_config.timeout = timeout
    try:
        return client.chat(messages, max_tokens=max_tokens, status_label=status_label)
    finally:
        client_config.timeout = original_timeout


def _extract_failed_paths(previous_patch: str, error: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for line in previous_patch.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            raw = line[6:].strip()
            if raw != "/dev/null" and raw not in seen:
                seen.add(raw)
                candidates.append(raw)

    path_pattern = re.compile(r"([A-Za-z0-9_.\-/]+\.py)(?::\d+)?")
    for match in path_pattern.findall(error):
        normalized = match.replace("\\", "/")
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    return candidates


def _retry_with_context_variants(
    *,
    client: OpenAICompatibleClient,
    task: str,
    workspace_root: Path,
    config: AgentConfig,
    variant: str,
    run_dir: Path | None,
    stage: str,
    status_prefix: str,
    prompt_builder: Callable[[str], list[dict[str, str]]],
    parse_response: Callable[[str], T],
    repair_response: Callable[[str, list[dict[str, str]], int], T],
) -> T:
    last_error: str | None = None
    for attempt, context in enumerate(
        _context_variants(workspace_root, task, config, variant=variant), start=1
    ):
        messages = prompt_builder(context)
        budget = _budget_for_messages(messages, config.llm.max_tokens)
        try:
            response = client.chat(
                messages, max_tokens=budget, status_label=f"{status_prefix} (attempt {attempt})"
            )
            try:
                result = parse_response(response.text)
                _log_llm_attempt(
                    run_dir,
                    stage,
                    attempt,
                    "success",
                    issue_type="unknown",
                    strategy="none",
                    max_tokens=budget,
                    context_chars=len(context),
                    response_text=response.text,
                )
                return result
            except ValueError as exc:
                last_error = str(exc)
                issue = "unknown"
                _log_llm_attempt(
                    run_dir,
                    stage,
                    attempt,
                    "parse_error",
                    issue_type=issue,
                    strategy=strategy_for_issue(issue),
                    error=last_error,
                    max_tokens=budget,
                    context_chars=len(context),
                    response_text=response.text,
                )
                return repair_response(response.text, messages, budget)
        except Exception as exc:
            issue = classify_httpx_exception(exc)
            last_error = _format_exception(exc)
            _log_llm_attempt(
                run_dir,
                stage,
                attempt,
                "request_error",
                issue_type=issue,
                strategy=strategy_for_issue(issue),
                error=last_error,
                max_tokens=budget,
                context_chars=len(context),
                response_text=_response_text_from_exception(exc),
            )
            if issue == "context_too_large":
                continue
            if attempt < 3:
                time.sleep(0.5 * attempt)
                continue
            break
    raise RuntimeError(f"{stage} generation failed after retries: {last_error or 'unknown error'}")


def _log_llm_attempt(
    run_dir: Path | None,
    stage: str,
    attempt: int,
    status: str,
    *,
    issue_type: str | None = None,
    strategy: str | None = None,
    error: str | None = None,
    max_tokens: int | None = None,
    context_chars: int | None = None,
    response_text: str | None = None,
) -> None:
    if run_dir is None:
        return
    # Sanitize raw model output and error text before it lands on disk so an
    # accidentally pasted token or Authorization header does not leak into
    # events.jsonl.  sanitize_log_text collapses whitespace, redacts known
    # secret markers, and clamps length.
    safe_error = sanitize_log_text(error) if error else None
    safe_excerpt = sanitize_log_text(response_text, limit=1000) if response_text else None
    append_jsonl(
        run_dir / "events.jsonl",
        {
            "timestamp": time.time(),
            "stage": stage,
            "attempt": attempt,
            "status": status,
            "issue_type": issue_type,
            "strategy": strategy,
            "error": safe_error,
            "max_tokens": max_tokens,
            "context_chars": context_chars,
            "response_excerpt": safe_excerpt,
        },
    )


def _response_text_from_exception(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    text = getattr(response, "text", None)
    if text:
        return text
    return None


def _format_exception(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        body = getattr(response, "text", "") or ""
        snippet = body[:400].replace("\n", " ").strip()
        return f"{exc.__class__.__name__} (status={status}): {snippet or str(exc)}"
    return f"{exc.__class__.__name__}: {exc}"

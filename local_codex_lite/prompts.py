from __future__ import annotations


def ask_prompt(
    question: str, context: str, evidence: str = "", rag_context: str = ""
) -> list[dict[str, str]]:
    has_evidence = bool(evidence.strip())
    has_rag = bool(rag_context.strip())
    return [
        {
            "role": "system",
            "content": (
                "You are an evidence-first coding assistant. "
                "Use only the evidence and retrieved context provided in the user message. "
                "If a value is not present, answer UNKNOWN. "
                "When RAG context is provided, cite file paths and line ranges explicitly. "
                "If the user asks to compare artifacts or check whether fields match, answer each requested field "
                "explicitly as MATCH, MISMATCH, or UNKNOWN. "
                "Do not invent numbers, file paths, findings, or CVEs."
            ),
        },
        {
            "role": "user",
            "content": (
                "Question:\n"
                f"{question}\n\n"
                "Context:\n"
                f"{context}\n\n"
                + (f"Evidence:\n{evidence}\n\n" if has_evidence else "")
                + (f"Retrieved RAG context:\n{rag_context}\n\n" if has_rag else "")
                + "Return a concise answer grounded only in the provided context. "
                + "If relevant code locations are known, cite them as `path:line-range`."
            ),
        },
    ]


def evidence_question_prompt(question: str, context: str, evidence: str) -> list[dict[str, str]]:
    return ask_prompt(question, context, evidence=evidence)


def evidence_context_block(evidence: str) -> str:
    return (
        "Evidence:\n"
        f"{evidence}\n\n"
        "Rules:\n"
        "- Treat the evidence block as ground truth.\n"
        "- If a fact is missing, do not infer it.\n"
        "- If a value is absent, answer UNKNOWN.\n"
        "- Do not invent CVEs, counts, snapshot IDs, file paths, or tool versions.\n"
    )


def plan_prompt(task: str, context: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent. Return only valid JSON matching the schema. "
                "If the task includes evidence, use it as ground truth and do not invent missing values."
            ),
        },
        {
            "role": "user",
            "content": (
                "Task:\n"
                f"{task}\n\n"
                "Workspace context:\n"
                f"{context}\n\n"
                "Return JSON only with keys summary, files_to_inspect, implementation_steps, risks, "
                "needs_clarification, clarifying_questions."
            ),
        },
    ]


def _runtime_fix_related_block(
    related_files: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> str:
    """Render a 'Related files (read-only context)' block for the runtime-fix
    prompts.  The model is told to patch only the primary target file; these
    related files exist so it can reason about the call chain.

    Each related file is truncated to ~2 KB so the prompt budget stays under
    control even when the traceback spans several modules.
    """
    if not related_files:
        return ""
    parts = ["", "Related files (read-only context; do NOT patch these):"]
    for rel_path, text in related_files:
        snippet = text if len(text) <= 2000 else text[:2000] + "\n... (truncated)"
        parts.append(f"\n--- {rel_path} ---\n{snippet}")
    return "\n".join(parts)


def runtime_fix_single_file_plan_prompt(
    task: str,
    target_path: str,
    traceback_text: str,
    current_text: str,
    related_files: tuple[tuple[str, str], ...] = (),
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent handling a single-file runtime repair.\n"
                "Return only valid JSON matching the schema.\n"
                "There is exactly one target file.\n"
                "Do not propose edits to any other file.\n"
                "Use the traceback as ground truth.\n"
                "The current file content is authoritative for what code exists right now.\n"
                "Do not describe, remove, or modify lines that are not present in the current file content.\n"
                "The fix must remove the reported runtime failure directly.\n"
                "Do not invent extra refactors or documentation work.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task:\n{task}\n\n"
                f"Target file:\n{target_path}\n\n"
                f"Traceback:\n{traceback_text}\n\n"
                f"Current file content:\n{current_text}\n"
                + _runtime_fix_related_block(related_files)
                + "\n\n"
                "Return JSON only with keys summary, files_to_inspect, implementation_steps, risks, "
                "needs_clarification, clarifying_questions.\n"
                "Important:\n"
                "- files_to_inspect should contain only the target file unless another file is strictly required.\n"
                "- The summary must say how the traceback will be eliminated.\n"
            ),
        },
    ]


def patch_prompt(task: str, plan_json: str, context: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent. Return only a unified diff, no markdown. "
                "Prefer creating or updating runnable code files over documentation. "
                "Do not return no-op diffs, comment-only diffs, or whitespace-only diffs. "
                "Do not edit cache directories like .pytest_cache. "
                "Do not edit README files unless the task explicitly asks for docs or launch instructions. "
                "Use git-root-relative file paths in the diff. "
                "If the workspace is nested under a repository root, preserve the workspace folder prefix in paths "
                "so git apply can locate the files correctly. "
                "If the task includes evidence, treat it as ground truth and do not invent missing values."
            ),
        },
        {
            "role": "user",
            "content": (
                "Task:\n"
                f"{task}\n\nPlan JSON:\n{plan_json}\n\nWorkspace context:\n{context}\n\n"
                "Return only unified diff. If the task is to create a runnable GUI demo, make sure the diff creates "
                "a launchable code file."
            ),
        },
    ]


def runtime_fix_single_file_patch_prompt(
    task: str,
    plan_json: str,
    target_path: str,
    traceback_text: str,
    current_text: str,
    related_files: tuple[tuple[str, str], ...] = (),
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent handling a single-file runtime repair.\n"
                "Return only a unified diff, no markdown.\n"
                "Touch only the target file unless absolutely necessary.\n"
                "Use the traceback as ground truth.\n"
                "The current file content is authoritative for what code exists right now.\n"
                "Do not claim to edit or replace statements that are not present in the current file content.\n"
                "The patch must directly eliminate the reported runtime failure.\n"
                "Do not return no-op diffs, comment-only diffs, whitespace-only diffs, placeholders, TODOs, or pass-based stubs.\n"
                "Do not delete working logic unrelated to the runtime failure.\n"
                "Use git-root-relative file paths.\n"
                "If you cannot produce a reliable diff, preserve exact code structure and make only the minimal concrete fix.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task:\n{task}\n\n"
                f"Plan JSON:\n{plan_json}\n\n"
                f"Target file:\n{target_path}\n\n"
                f"Traceback:\n{traceback_text}\n\n"
                f"Current file content:\n{current_text}\n"
                + _runtime_fix_related_block(related_files)
                + "\n\n"
                "Return only unified diff.\n"
                "Proof requirement: after the patch, the exact traceback above should no longer occur for the same reason.\n"
            ),
        },
    ]


def patch_repair_prompt(
    task: str, plan_json: str, previous_patch: str, error: str, context: str
) -> list[dict[str, str]]:
    return patch_repair_prompt_for_issue(
        "generic_retry", task, plan_json, previous_patch, error, context
    )


def patch_repair_prompt_for_issue(
    issue_type: str,
    task: str,
    plan_json: str,
    previous_patch: str,
    error: str,
    context: str,
    *,
    repair_attempt: int = 1,
) -> list[dict[str, str]]:
    system_text = {
        "malformed_diff": (
            "You repair malformed unified diffs for a local coding agent.\n"
            "Return only a valid unified diff.\n"
            "Do not include markdown fences, explanations, or commentary.\n"
            "Use correct ---/+++ headers and @@ hunk headers that match the changed line counts.\n"
            "Keep the patch minimal and syntactically valid for git apply.\n"
            "Use git-root-relative file paths.\n"
            "If the workspace is nested under a repository root, preserve the workspace folder prefix in paths."
        ),
        "context_mismatch": (
            "You repair unified diffs that do not apply to the current files.\n"
            "Return only a valid unified diff.\n"
            "Regenerate the patch against the current workspace context.\n"
            "Do not repeat the same hunk layout if the previous diff already failed to apply.\n"
            "Prefer updating the exact current lines shown in the workspace context.\n"
            "Do not include markdown fences, explanations, or commentary.\n"
            "Use git-root-relative file paths.\n"
            "If the workspace is nested under a repository root, preserve the workspace folder prefix in paths."
        ),
        "file_already_exists": (
            "You repair create-new-file diffs when the target file already exists.\n"
            "Return only a valid unified diff.\n"
            "If the file exists, update the existing file instead of creating it from /dev/null.\n"
            "If the previous patch mixed file creation with unrelated edits, drop the unrelated edits.\n"
            "Do not include markdown fences, explanations, or commentary.\n"
            "Use git-root-relative file paths.\n"
            "If the workspace is nested under a repository root, preserve the workspace folder prefix in paths."
        ),
        "target_drift": (
            "You repair unified diffs that drifted away from the intended target file.\n"
            "Return only a valid unified diff.\n"
            "The intended target file in the workspace context is authoritative.\n"
            "Ignore unrelated paths from the previous patch.\n"
            "If the intended target file does not exist yet, create only that file from /dev/null.\n"
            "Do not include markdown fences, explanations, or commentary.\n"
            "Use git-root-relative file paths.\n"
            "If the workspace is nested under a repository root, preserve the workspace folder prefix in paths."
        ),
        "path_mismatch": (
            "You repair unified diffs that target the wrong paths.\n"
            "Return only a valid unified diff.\n"
            "Use git-root-relative paths only, with no absolute paths and no unrelated prefixes.\n"
            "Only touch files inside the workspace.\n"
            "If the workspace folder is nested under a repository root, the diff paths must include that folder prefix."
        ),
        "empty_patch": (
            "You repair empty patch responses for a local coding agent.\n"
            "Return only a non-empty unified diff when code changes are needed.\n"
            "If no changes are needed, return an empty response; the agent will not apply it.\n"
            "Do not include markdown fences or explanations.\n"
            "Use git-root-relative file paths."
        ),
        "generic_retry": (
            "You repair unified diffs for a local coding agent.\n"
            "Return only a valid unified diff.\n"
            "Do not include markdown fences, explanations, or commentary.\n"
            "Keep the patch minimal and runnable.\n"
            "The diff must be syntactically valid for git apply.\n"
            "If the previous patch failed to apply, produce a materially different corrected diff instead of repeating it.\n"
            "Use git-root-relative file paths.\n"
            "If the workspace is nested under a repository root, preserve the workspace folder prefix in paths."
        ),
    }.get(
        issue_type,
        "You repair unified diffs for a local coding agent.\nReturn only a valid unified diff.",
    )

    return [
        {
            "role": "system",
            "content": system_text,
        },
        {
            "role": "user",
            "content": (
                f"Issue type: {issue_type}\n\n"
                f"Task:\n{task}\n\n"
                f"Plan:\n{plan_json}\n\n"
                f"Workspace context:\n{context}\n\n"
                f"Previous patch:\n{previous_patch}\n\n"
                f"git apply error:\n{error}\n\n"
                f"Repair attempt: {repair_attempt}\n\n"
                "Return a corrected unified diff only.\n"
                "If the previous patch touched the wrong lines, wrong file mode, or wrong path, fix that directly.\n"
                "If this is not the first repair attempt, do not return the same diff shape again.\n"
                "Important: the diff must use git-root-relative file paths. "
                "If the workspace is nested under a repository root, include the workspace folder prefix in each path."
            ),
        },
    ]


def command_prompt(task: str, plan_json: str, context: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent. Return only valid JSON matching the schema. "
                "Each cmd value must be a literal executable shell command, not a prose instruction. "
                "The environment is Windows PowerShell, so do not use Unix-only tools such as sed, bash, or chmod. "
                "If no safe executable command is appropriate, return an empty commands list."
            ),
        },
        {
            "role": "user",
            "content": (
                "Task:\n"
                f"{task}\n\nPlan JSON:\n{plan_json}\n\nWorkspace context:\n{context}\n\n"
                "Return JSON only with key commands as a list of {cmd, reason, risk}. "
                "Use concrete commands such as `python path/to/file.py` or `pytest tests/test_name.py`. "
                "Do not return English task descriptions in cmd."
            ),
        },
    ]


def review_prompt(
    diff_text: str, context: str, base_ref: str = "working tree", head_ref: str = "HEAD"
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a senior code reviewer. Review the provided diff and workspace context only. "
                "Focus on correctness, regressions, security, missing tests, maintainability, and rollout risk. "
                "Return only valid JSON. "
                "If a fact is not present, use UNKNOWN. "
                "Do not invent file paths, line numbers, findings, or approvals. "
                "If the diff is empty, report that there is nothing to review."
            ),
        },
        {
            "role": "user",
            "content": (
                "Review target:\n"
                f"{base_ref}...{head_ref}\n\n"
                "Diff:\n"
                f"{diff_text}\n\n"
                "Workspace context:\n"
                f"{context}\n\n"
                "Return JSON only with keys summary, overall_risk, findings, positives, missing_context, recommendation.\n"
                "Each finding should be an object with keys severity, file, line, title, detail, suggestion."
            ),
        },
    ]


def runtime_fix_single_file_command_prompt(
    task: str, plan_json: str, target_path: str
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent. Return only valid JSON matching the schema.\n"
                "Each cmd value must be a literal executable shell command for Windows PowerShell.\n"
                "Do not return prose, editors, or Unix-only tools.\n"
                "Prefer a minimal command sequence that verifies the runtime fix.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task:\n{task}\n\n"
                f"Plan JSON:\n{plan_json}\n\n"
                f"Target file:\n{target_path}\n\n"
                "Return JSON only with key commands as a list of {cmd, reason, risk}.\n"
                f"The primary verification command should run the target file, for example `python {target_path}`.\n"
                "Return an empty commands list if no safe command is appropriate.\n"
            ),
        },
    ]


def clarification_answers_prompt(
    task: str, plan_json: str, context: str, qa_pairs: list[tuple[str, str]]
) -> list[dict[str, str]]:
    answers_text = (
        "\n".join(f"Q: {question}\nA: {answer}" for question, answer in qa_pairs)
        if qa_pairs
        else "No answers provided."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent. The user answered the plan's clarifying "
                "questions; their answers are ground truth. "
                "Return only valid JSON matching the schema."
            ),
        },
        {
            "role": "user",
            "content": (
                "Task:\n"
                f"{task}\n\n"
                "Existing plan:\n"
                f"{plan_json}\n\n"
                "Clarification answers from the user:\n"
                f"{answers_text}\n\n"
                "Workspace context:\n"
                f"{context}\n\n"
                "Revise the plan strictly following the user's answers, set needs_clarification "
                "to false, and return JSON only with keys summary, files_to_inspect, "
                "implementation_steps, risks, needs_clarification, clarifying_questions."
            ),
        },
    ]


def assumption_prompt(
    task: str, plan_json: str, context: str, questions: list[str]
) -> list[dict[str, str]]:
    questions_text = (
        "\n".join(f"- {q}" for q in questions) if questions else "- No questions provided."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are a precise coding agent. The user asked you to continue with reasonable assumptions. "
                "Return only valid JSON matching the schema."
            ),
        },
        {
            "role": "user",
            "content": (
                "Task:\n"
                f"{task}\n\n"
                "Existing plan:\n"
                f"{plan_json}\n\n"
                "Clarifying questions:\n"
                f"{questions_text}\n\n"
                "Workspace context:\n"
                f"{context}\n\n"
                "Revise the plan with reasonable assumptions, set needs_clarification to false, and return JSON only "
                "with keys summary, files_to_inspect, implementation_steps, risks, needs_clarification, clarifying_questions."
            ),
        },
    ]

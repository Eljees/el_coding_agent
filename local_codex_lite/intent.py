from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .capabilities import Capability


@dataclass(frozen=True)
class IntentDecision:
    can_do: str
    intent: str
    confidence: float
    human_summary: str
    safe_next_action: str
    # The following sequence fields are immutable (tuples) on purpose so that
    # IntentDecision instances stay genuinely frozen -- list fields on a
    # ``frozen=True`` dataclass can still be mutated in place which silently
    # breaks identity assumptions in callers.
    required_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    requires_apply: bool
    requires_exec: bool
    requires_external_help: bool
    risks: tuple[str, ...]
    cli_equivalent: str
    capability_id: str
    matched_keywords: tuple[str, ...]


def decision_as_dict(decision: IntentDecision) -> dict:
    return asdict(decision)


def recognize_intent(user_text: str, capabilities: list[Capability]) -> IntentDecision:
    text = user_text.strip()
    lower = text.lower()
    if not text:
        return _fallback_decision(
            "needs_input", "unknown", "Describe the task first.", "Enter a task to analyze."
        )

    if not capabilities:
        # Defensive: built-ins are always present today, but guard against a
        # misconfigured registry so the `max(..., default=(0, capabilities[0], …))`
        # below can never raise IndexError on an empty list.
        return _fallback_decision(
            "needs_input",
            "unknown",
            "No capabilities are registered to handle this task.",
            "Check the capability registry or reinstall plugins.",
        )

    scored: list[tuple[int, Capability, list[str]]] = []
    for capability in capabilities:
        matched = [keyword for keyword in capability.keywords if keyword in lower]
        score = len(matched)
        if capability.id == "review.code" and re.search(r"\bpr\b", lower):
            matched.append("phrase:pr")
            score += 2
        if capability.id == "logs.latest" and (
            "покажи последние логи" in lower or "latest logs" in lower
        ):
            matched.append("phrase:latest logs")
            score += 2
        if capability.id == "evidence.json_compare" and _looks_like_two_json_paths(lower):
            matched.append("pattern:two json paths")
            score += 2
        if capability.id == "evidence.artifacts.inspect" and _looks_like_artifact_path(text):
            matched.append("pattern:artifact path")
            score += 2
        if capability.id == "evidence.cve_scan" and _looks_like_artifact_path(text):
            matched.append("pattern:cve artifact path")
            score += 2
        if capability.id == "evidence.cve_scan" and any(
            marker in lower for marker in ("cve", "cve-bin-tool", "уязвим")
        ):
            matched.append("phrase:cve scan")
            score += 3
        if capability.id == "appsechub.issues" and any(
            marker in lower for marker in ("appsechub", "апсекхаб", "аппсекхаб", "appprofile")
        ):
            # An explicit Hub mention must outweigh cve_scan's "уязвим" bonus:
            # "уязвимости приложения 89 в апсекхабе" is a Hub query, not a
            # local artifact scan.
            matched.append("phrase:appsechub app")
            score += 4
        scored.append((score, capability, matched))

    score, capability, matched_keywords = max(
        scored, key=lambda item: item[0], default=(0, capabilities[0], [])
    )
    if score <= 0:
        return _fallback_decision(
            "partial",
            "unknown",
            "I can help, but the task does not map cleanly to a known safe capability yet.",
            "Start with preview, ask, logs, evidence, or doctor.",
        )

    missing_inputs = _missing_inputs(capability, text)
    can_do = "yes" if not missing_inputs else "needs_input"
    summary = capability.description
    if capability.id == "run.preview":
        summary = "Inspect a code-change request safely before applying anything."
    if capability.id == "review.code":
        summary = "Review code changes or a pull request without modifying files."
    if capability.id == "evidence.json_compare":
        summary = "Compare two JSON files or reports and summarize the differences."
    safe_next_action = capability.cli_equivalent
    if capability.id == "evidence.json_compare" and missing_inputs:
        safe_next_action = "Provide the two JSON paths, then run evidence json-compare."
    if capability.id == "review.code":
        safe_next_action = "Run python -m local_codex_lite review to inspect the current diff."
    if capability.id == "evidence.artifacts.inspect":
        summary = "Inventory archive artifacts and extract them safely into an evidence bundle."
        if missing_inputs:
            safe_next_action = "Provide an artifact directory or archive path, then run evidence artifacts inspect."
    if capability.id == "evidence.cve_scan":
        summary = (
            "Run cve-bin-tool on artifacts, keep evidence, and generate a high/critical report."
        )
        if missing_inputs:
            safe_next_action = (
                "Provide an artifact directory or archive path, then run evidence cve-scan."
            )
    confidence = min(0.45 + 0.08 * score, 0.95)
    risks = []
    if capability.requires_apply:
        risks.append("writes changes to disk only when --apply is used")
    if capability.requires_exec:
        risks.append("runs suggested commands only when --exec is used")
    return IntentDecision(
        can_do=can_do,
        intent=capability.id,
        confidence=round(confidence, 2),
        human_summary=summary,
        safe_next_action=safe_next_action,
        required_inputs=tuple(capability.required_inputs),
        missing_inputs=tuple(missing_inputs),
        requires_apply=capability.requires_apply,
        requires_exec=capability.requires_exec,
        requires_external_help=False,
        risks=tuple(risks),
        cli_equivalent=capability.cli_equivalent,
        capability_id=capability.id,
        matched_keywords=tuple(matched_keywords),
    )


def _fallback_decision(can_do: str, intent: str, summary: str, next_action: str) -> IntentDecision:
    return IntentDecision(
        can_do=can_do,
        intent=intent,
        confidence=0.2,
        human_summary=summary,
        safe_next_action=next_action,
        required_inputs=(),
        missing_inputs=(),
        requires_apply=False,
        requires_exec=False,
        requires_external_help=False,
        risks=(),
        cli_equivalent="",
        capability_id=intent,
        matched_keywords=(),
    )


def _looks_like_two_json_paths(text: str) -> bool:
    return len(re.findall(r"\b[\w./\\-]+\.json\b", text)) >= 2


def extract_artifact_input_path(text: str) -> str:
    paths = extract_artifact_paths(text)
    return paths[0] if paths else ""


def extract_artifact_output_path(text: str) -> str:
    paths = extract_artifact_paths(text)
    return paths[1] if len(paths) >= 2 else ""


def extract_artifact_paths(text: str) -> list[str]:
    candidates: list[str] = []
    for pattern in (
        r'"(?P<path>[A-Za-z]:\\[^"]+)"',
        r"'(?P<path>[A-Za-z]:\\[^']+)'",
        r"(?P<path>[A-Za-z]:\\[^\s\r\n\"')\]}]+)",
    ):
        for match in re.finditer(pattern, text):
            raw = match.group("path").strip().rstrip(" .;,)]}")
            if raw and raw not in candidates:
                candidates.append(raw)
    return candidates


def _looks_like_artifact_path(text: str) -> bool:
    return bool(extract_artifact_input_path(text))


# Inputs that are satisfied by a Windows filesystem path in the task text.
_PATH_INPUTS = {"input_root", "left", "right"}
# Inputs that require two JSON-like filenames (not necessarily Windows paths).
_JSON_PATH_INPUTS = {"left_path", "right_path"}
# Inputs that accept either a repo URL or a local file path holding a repo list.
_REPO_URL_OR_FILE_INPUTS = {"repo_url_or_file"}


_URL_RE = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
_REPO_LIST_FILE_RE = re.compile(r"\S+\.(?:txt|list|lst)\b", re.IGNORECASE)


def _looks_like_repo_input(text: str) -> bool:
    """Return True when *text* contains something that can be used as the
    `--repo-url` or `--repo-file` argument for the TruffleHog scan capability.

    The check is intentionally permissive: a plain http(s) URL, a Windows-style
    path, or a tokenized .txt/.list filename all qualify.  False positives on
    this routing layer are cheap (CLI re-validates), false negatives let the
    UI claim a missing-input task can run.
    """
    if _URL_RE.search(text):
        return True
    if extract_artifact_paths(text):
        return True
    if _REPO_LIST_FILE_RE.search(text):
        return True
    return False


def _missing_inputs(capability: Capability, text: str) -> list[str]:
    """Return required inputs that cannot be found in *text*.

    Derives the check from ``capability.required_inputs`` so no capability IDs
    are hard-coded here.  Adding a new capability that lists ``required_inputs``
    automatically gets free validation.
    """
    missing: list[str] = []
    paths = extract_artifact_paths(text)

    path_idx = 0  # position counter for ordered path requirements
    for required in capability.required_inputs:
        if required in _PATH_INPUTS:
            if len(paths) <= path_idx:
                missing.append(required)
            path_idx += 1
        elif required in _JSON_PATH_INPUTS:
            if not _looks_like_two_json_paths(text.lower()):
                missing.append(required)
        elif required in _REPO_URL_OR_FILE_INPUTS:
            if not _looks_like_repo_input(text):
                missing.append(required)
    return missing

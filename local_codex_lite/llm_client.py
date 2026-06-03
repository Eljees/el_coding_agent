from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from .config import LLMConfig


@dataclass
class LLMResponse:
    text: str
    raw: dict


@runtime_checkable
class SupportsChat(Protocol):
    """Structural type for the one seam the LLM is reached through.

    Both the real :class:`OpenAICompatibleClient` and the lightweight test
    doubles in the suite satisfy this protocol, so planner/runner code can be
    driven with any conforming object.  A double only needs ``chat``.
    """

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = ...,
        status_label: str | None = ...,
    ) -> LLMResponse: ...


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        status_label: str | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
        }
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                return self._request_with_heartbeat(payload, status_label=status_label)
            except Exception as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(str(last_error))

    def _request_with_heartbeat(
        self, payload: dict, status_label: str | None = None
    ) -> LLMResponse:
        stop_event = threading.Event()
        heartbeat = None
        completed = False
        if status_label:
            self._emit_status(f"{status_label}...")
            heartbeat = threading.Thread(
                target=self._heartbeat_loop,
                args=(stop_event, status_label),
                daemon=True,
            )
            heartbeat.start()
        try:
            with httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout) as client:
                resp = client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                completed = True
                return LLMResponse(text=text, raw=data)
        finally:
            stop_event.set()
            if status_label and completed:
                self._emit_status(f"{status_label} done")

    def _heartbeat_loop(self, stop_event: threading.Event, status_label: str) -> None:
        while not stop_event.wait(15.0):
            self._emit_status(f"{status_label}... still working")

    def _emit_status(self, message: str) -> None:
        try:
            sys.stderr.write(f"{message}\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            # Status output is best-effort only. It must not break the LLM request path.
            return

    def healthcheck(self) -> dict:
        messages = [
            {"role": "system", "content": "Answer only with the word pong."},
            {"role": "user", "content": "ping"},
        ]
        resp = self.chat(messages)
        return {"text": resp.text, "raw": resp.raw}


def extract_json(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise ValueError("LLM returned empty text instead of JSON")

    if stripped.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
        if match:
            stripped = match.group(1).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = stripped[start : end + 1]
            return json.loads(candidate)
        raise ValueError(f"LLM did not return valid JSON: {stripped[:200]!r}") from None


def repair_json_response(
    client: OpenAICompatibleClient,
    original_messages: list[dict[str, str]],
    bad_text: str,
    max_tokens: int,
) -> dict:
    repair_messages = [
        *original_messages,
        {
            "role": "user",
            "content": (
                "Your previous answer was invalid.\n"
                "Return only valid JSON. No markdown, no explanation.\n\n"
                f"Invalid answer:\n{bad_text}"
            ),
        },
    ]
    response = client.chat(
        repair_messages, max_tokens=max_tokens, status_label="Repairing model output"
    )
    return extract_json(response.text)


def extract_diff(text: str) -> str:
    # Trim only outer whitespace (and leading newlines) without touching trailing
    # whitespace on individual lines: a context line representing an empty source
    # line is encoded as a single leading space, and a global ``.strip()`` would
    # silently destroy it -> normalize_unified_diff would then reject the hunk.
    stripped = text.strip("\n").rstrip()
    if not stripped.strip():
        raise ValueError("LLM returned empty text instead of a diff")

    # Search for a fenced code block anywhere in the text (model may add prose before it).
    # Tolerant: closing fence may be at end-of-string without trailing newline.
    fence_match = re.search(
        r"```(?:diff|patch)?[ \t]*\r?\n(?P<body>.*?)(?:\r?\n[ \t]*```|$)",
        stripped,
        re.DOTALL | re.IGNORECASE,
    )
    if fence_match:
        stripped = fence_match.group("body").rstrip("\n")

    # Locate the start of the diff but preserve the rest of the text byte-for-byte
    # apart from leading empty lines.
    start = stripped.find("diff --git ")
    if start != -1:
        stripped = stripped[start:]
    stripped = _drop_leading_blank_lines(stripped).rstrip("\n")

    if "diff --git " not in stripped and not stripped.startswith("--- a/"):
        raise ValueError(f"LLM did not return a usable diff: {stripped[:200]!r}")

    return normalize_unified_diff(stripped)


def _drop_leading_blank_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@(?P<tail>.*)$"
)


def normalize_unified_diff(diff_text: str) -> str:
    lines = diff_text.splitlines()
    normalized: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("@@ "):
            normalized.append(line)
            i += 1
            continue

        match = _HUNK_HEADER_RE.match(line)
        if not match:
            raise ValueError(f"Invalid unified diff hunk header: {line!r}")

        body: list[str] = []
        i += 1
        while i < len(lines):
            candidate = lines[i]
            if candidate.startswith("diff --git ") or candidate.startswith("@@ "):
                break
            body.append(candidate)
            i += 1

        old_count = 0
        new_count = 0
        normalized_body: list[str] = []
        for body_line in body:
            if body_line.startswith("\\ No newline at end of file"):
                # Preserve the marker but do not count it as a content line.
                normalized_body.append(body_line)
                continue
            # An empty line inside a hunk is a legitimate context line: it
            # represents an empty source line whose canonical encoding is a
            # single leading space. Many transports (JSON serializers,
            # pretty-printers, the model itself) strip trailing whitespace and
            # collapse " " -> "". Treat both spellings as a context line and
            # re-emit the canonical " " form so ``git apply`` is happy.
            if body_line == "":
                old_count += 1
                new_count += 1
                normalized_body.append(" ")
                continue
            # A closing markdown fence leaking into the hunk marks the real end.
            if body_line.startswith("```"):
                break
            prefix = body_line[0]
            if prefix == " ":
                old_count += 1
                new_count += 1
                normalized_body.append(body_line)
            elif prefix == "-":
                old_count += 1
                normalized_body.append(body_line)
            elif prefix == "+":
                new_count += 1
                normalized_body.append(body_line)
            else:
                raise ValueError(f"Unexpected unified diff line: {body_line!r}")

        old_start = int(match.group("old_start"))
        new_start = int(match.group("new_start"))
        tail = match.group("tail") or ""
        normalized.append(
            "@@ "
            f"-{_format_range(old_start, old_count)} "
            f"+{_format_range(new_start, new_count)} @@"
            f"{tail}"
        )
        normalized.extend(normalized_body)

    return "\n".join(normalized) + ("\n" if normalized else "")


def _format_range(start: int, count: int) -> str:
    return f"{start}" if count == 1 else f"{start},{count}"

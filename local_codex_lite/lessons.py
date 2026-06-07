"""Lessons memory: short, prompt-ready reminders that keep a weak local model
from repeating the same generation mistakes.

A qwen-class model keeps stepping on the same rakes -- inventing tkinter
keyword arguments, importing third-party modules that do not exist, shipping
broken indentation, or returning mutable default arguments.  Two sources feed
the reminders this module produces:

* ``CURATED_PITFALLS`` -- a hand-written list of recurring rakes keyed by
  trigger keywords.  These fire whenever the task text mentions the relevant
  topic, so the model is warned *before* it makes the mistake.
* A learned ledger at ``<workspace>/.local-codex-lite/lessons.jsonl`` -- one
  JSON object per line, appended by :func:`record_lesson` whenever the repair
  loop recovered from a real failure in this workspace.  Future runs whose task
  text overlaps with a past failure get a tailored reminder.

The public surface (:func:`relevant_lessons`, :func:`lessons_guardrail_block`)
returns *short* strings on purpose: a long context actively hurts a small model,
so reminders are capped hard.

Deliberately Tk-free and LLM-free -- pure file + string work, callable from any
stage (and from tests) without dragging in a UI or an HTTP client.  Every read
tolerates a missing/corrupt store by falling back to empty rather than crashing
the run, and :func:`record_lesson` never raises.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

# Tunables -----------------------------------------------------------------
_STORE_DIRNAME = ".local-codex-lite"
_STORE_FILENAME = "lessons.jsonl"
_EXCERPT_CHARS = 200
_SIGNATURE_CHARS = 160
_DEDUP_WINDOW = 50  # skip a learned record if its signature repeats within last N
_MAX_FILE_RECORDS = 500  # cap the ledger; oldest records are dropped past this
_DEFAULT_LOAD_LIMIT = 50

# Lines that look like the final "ExceptionType: message" of a traceback.
_EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Warning|Interrupt|Exit)\b")

# Signature normalization (applied in order: quoted values, paths, numbers) so
# incidental detail collapses into a stable dedupe key.
_QUOTED = re.compile(r"""(['"]).*?\1""")
_PATH = re.compile(
    r"(?:[A-Za-z]:)?[\w.\-]*[\\/][\w.\-\\/]*|\b[\w.\-]+\.(?:py|txt|json|cfg|ini|toml|yaml|yml)\b"
)
_NUMBER = re.compile(r"\d+")

# Significant-word extraction for learned-lesson relevance matching: a word of
# four or more characters that is not a common filler token.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_STOPWORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "into",
        "your",
        "then",
        "when",
        "else",
        "have",
        "make",
        "need",
        "want",
        "code",
        "file",
        "files",
        "please",
        "should",
        "would",
        "could",
    }
)


@dataclass(frozen=True)
class Lesson:
    """A curated pitfall: fires when any *trigger_keyword* is in the task text."""

    trigger_keywords: tuple[str, ...]
    signature: str
    guidance: str


@dataclass(frozen=True)
class LearnedLesson:
    """One persisted failure-then-recovery record from this workspace."""

    ts: float
    error_code: str
    signature: str
    detail_excerpt: str
    task_excerpt: str


# Hand-curated rakes a small model trips on repeatedly.  Keep guidance terse:
# one or two sentences, concrete, actionable.
CURATED_PITFALLS: tuple[Lesson, ...] = (
    Lesson(
        trigger_keywords=("tkinter", "tk.", "ttk", "messagebox", "widget"),
        signature="tkinter-unknown-option",
        guidance=(
            "tkinter widgets (tk.Button/Label/Entry) accept only documented options; "
            "there is no 'contextmenu' option -- bind right-click via "
            ".bind('<Button-3>', handler)."
        ),
    ),
    Lesson(
        trigger_keywords=("import", "package", "module", "library", "dependency", "pip"),
        signature="invented-import",
        guidance=(
            "Import only the standard library or packages already present in the workspace; "
            "do not invent package names or assume third-party installs."
        ),
    ),
    Lesson(
        trigger_keywords=("f-string", "format", "fstring", "string", "print", "template"),
        signature="fstring-quote-clash",
        guidance=(
            "Do not reuse the same quote character inside an f-string expression; "
            "use the other quote style or precompute the value in a variable."
        ),
    ),
    Lesson(
        trigger_keywords=("def ", "function", "parameter", "argument", "default", "list", "dict"),
        signature="mutable-default-arg",
        guidance=(
            "Never use a mutable default argument (def f(x=[])); default to None and "
            "create the list/dict inside the function body."
        ),
    ),
    Lesson(
        trigger_keywords=("open(", "read", "write", "file", "encoding", "csv", "json"),
        signature="missing-encoding",
        guidance=(
            "On Windows always pass encoding='utf-8' to open(); the default code page "
            "corrupts non-ASCII text and breaks round-trips."
        ),
    ),
    Lesson(
        trigger_keywords=("subprocess", "shell", "command", "powershell", "run", "os.system"),
        signature="windows-shell-tooling",
        guidance=(
            "Target Windows PowerShell: do not call Unix-only tools (sed, bash, chmod, rm) "
            "and prefer subprocess.run with an argument list over shell=True."
        ),
    ),
    Lesson(
        trigger_keywords=("indent", "indentation", "tab", "block", "loop", "class"),
        signature="indentation-error",
        guidance=(
            "Keep indentation consistent (4 spaces, never tabs) and make sure every "
            "block opened by a colon has a body before emitting the diff."
        ),
    ),
)


def _store_path(root: Path) -> Path:
    return Path(root) / _STORE_DIRNAME / _STORE_FILENAME


def _excerpt(text: str) -> str:
    """Collapse whitespace and clamp to ``_EXCERPT_CHARS`` for compact storage."""
    flat = " ".join((text or "").split())
    return flat[:_EXCERPT_CHARS]


def _meaningful_line(detail: str) -> str:
    """Pick the most diagnostic single line from *detail*.

    For a traceback this is the final ``ExceptionType: message`` line; we scan
    from the bottom so nested tracebacks resolve to the outermost failure, and
    fall back to the first non-empty line when no exception line is present.
    """
    lines = [line.strip() for line in detail.replace("\r", "\n").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    for line in reversed(lines):
        if _EXCEPTION_LINE.match(line):
            return line
    return lines[0]


def _signature(detail: str) -> str:
    """Normalized, lowercased fold of *detail*'s key line; the dedupe key."""
    line = _meaningful_line(detail)[:_SIGNATURE_CHARS].lower()
    line = _QUOTED.sub("<val>", line)
    line = _PATH.sub("<path>", line)
    line = _NUMBER.sub("<n>", line)
    return " ".join(line.split())


def _significant_words(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text or "") if word.lower() not in _STOPWORDS}


def _read_raw(root: Path) -> list[dict]:
    """Read the JSONL ledger into dicts; tolerate missing/corrupt lines."""
    path = _store_path(root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _append_line(root: Path, entry: dict) -> None:
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _rewrite(root: Path, records: list[dict]) -> None:
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    tmp.replace(path)


def record_lesson(root: Path, *, error_code: str, detail: str, task: str) -> None:
    """Append one failure-then-recovery record to the workspace ledger.

    *detail* and *task* are collapsed and clamped to ``_EXCERPT_CHARS``; the
    dedupe *signature* is the normalized key line of *detail*.  A record whose
    signature already appears within the last ``_DEDUP_WINDOW`` entries is
    skipped, and the ledger is capped at ``_MAX_FILE_RECORDS`` (oldest dropped).

    Best-effort: any error (including a write failure) is swallowed so lessons
    memory can never take down a run.
    """
    try:
        signature = _signature(detail or "")
        if not signature:
            return
        records = _read_raw(root)
        recent = records[-_DEDUP_WINDOW:]
        if any(record.get("signature") == signature for record in recent):
            return
        entry = {
            "ts": time.time(),
            "error_code": str(error_code or ""),
            "signature": signature,
            "detail_excerpt": _excerpt(detail or ""),
            "task_excerpt": _excerpt(task or ""),
        }
        records.append(entry)
        if len(records) > _MAX_FILE_RECORDS:
            _rewrite(root, records[-_MAX_FILE_RECORDS:])
        else:
            _append_line(root, entry)
    except Exception:
        # Lessons memory is advisory; never let it break a run.
        return


def load_learned(root: Path, limit: int = _DEFAULT_LOAD_LIMIT) -> list[LearnedLesson]:
    """Return up to *limit* learned lessons, most recent first."""
    records = _read_raw(root)
    lessons: list[LearnedLesson] = []
    for record in records:
        signature = record.get("signature")
        if not isinstance(signature, str) or not signature:
            continue
        ts_raw = record.get("ts", 0.0)
        ts = float(ts_raw) if isinstance(ts_raw, (int, float)) else 0.0
        lessons.append(
            LearnedLesson(
                ts=ts,
                error_code=str(record.get("error_code", "") or ""),
                signature=signature,
                detail_excerpt=str(record.get("detail_excerpt", "") or ""),
                task_excerpt=str(record.get("task_excerpt", "") or ""),
            )
        )
    lessons.reverse()  # newest first
    if limit >= 0:
        return lessons[:limit]
    return lessons


def clear_learned(root: Path) -> int:
    """Delete the learned ledger; return how many records were removed."""
    path = _store_path(root)
    count = len(_read_raw(root))
    try:
        path.unlink()
    except OSError:
        return 0
    return count


def _learned_guidance(lesson: LearnedLesson) -> str:
    """A short reminder string derived from a persisted failure record."""
    code = lesson.error_code or "previous error"
    detail = lesson.detail_excerpt or lesson.signature
    return f"Earlier in this workspace a `{code}` was hit and fixed: {detail}"


def relevant_lessons(root: Path, task: str, *, max_items: int = 3) -> list[str]:
    """Select short reminder strings relevant to *task*.

    Curated pitfalls whose ``trigger_keywords`` appear in ``task.lower()`` come
    first, followed by learned lessons whose ``task_excerpt`` shares at least one
    significant word with *task*.  Returns up to *max_items* unique strings.
    """
    if max_items <= 0:
        return []
    task_lower = (task or "").lower()
    task_words = _significant_words(task)
    selected: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            selected.append(text)

    for lesson in CURATED_PITFALLS:
        if len(selected) >= max_items:
            break
        if any(keyword.lower() in task_lower for keyword in lesson.trigger_keywords):
            _add(lesson.guidance)

    if len(selected) < max_items and task_words:
        for learned in load_learned(root):
            if len(selected) >= max_items:
                break
            if task_words & _significant_words(learned.task_excerpt):
                _add(_learned_guidance(learned))

    return selected[:max_items]


def lessons_guardrail_block(root: Path, task: str, *, max_items: int = 3) -> str:
    """Render relevant reminders as a short prompt block, or "" when none."""
    items = relevant_lessons(root, task, max_items=max_items)
    if not items:
        return ""
    bullet_lines = "\n".join(f"- {item}" for item in items)
    return f"Known pitfalls to avoid:\n{bullet_lines}"

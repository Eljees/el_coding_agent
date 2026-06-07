"""Per-run attempt timelines and lessons-effectiveness statistics.

The owner wants to *see* the weak local model learn.  The raw material already
exists -- every run writes ``.local-codex-lite/runs/<id>/events.jsonl`` (one
JSON object per plan/patch attempt) plus ``result.json`` and the
``*_issue.json`` / ``failure.json`` error artifacts.  This module turns those
files into two read-only views:

- :func:`build_attempt_timeline` / :func:`render_timeline` -- the story of one
  run: every stage attempt, what failed and why, and the final outcome
  ("result: applied after 2 repairs").  Backs ``logs attempts`` and the GUI
  Runs tab.
- :func:`lessons_stats` / :func:`render_lessons_stats` -- did a recorded lesson
  actually stick?  For every record in ``lessons.jsonl`` we count how often its
  error signature occurred in runs *before* the lesson was written versus
  *after* it.  Zero recurrences after means the lesson is holding.  Backs
  ``lessons stats``.

Deliberately Tk-free, rich-free and LLM-free: pure file + string work returning
plain dataclasses and ``str``, so both the CLI and the GUI can reuse it and the
whole surface is unit-testable.  Every read tolerates missing or corrupt files
by skipping them -- reporting must never crash on a half-written run.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .lessons import load_learned, signature_for_detail

_TASK_EXCERPT_CHARS = 80
_DETAIL_EXCERPT_CHARS = 120
_SIGNATURE_RENDER_CHARS = 60
_TOP_SIGNATURES = 5

# Event statuses that represent a real failed attempt (planner-side LLM
# failures plus the patch pipeline's validation/apply/post-apply errors).
_FAILURE_STATUSES = frozenset({"patch_error", "parse_error", "request_error"})


@dataclass(frozen=True)
class TimelineRow:
    """One event from ``events.jsonl`` rendered as a timeline entry."""

    stage: str
    attempt: int
    status: str
    error_code: str | None = None
    detail_excerpt: str | None = None


@dataclass(frozen=True)
class RunReport:
    """The attempt timeline of a single run directory."""

    run_id: str
    task_excerpt: str
    rows: list[TimelineRow]
    final_status: str
    repair_count: int


@dataclass(frozen=True)
class LessonStat:
    """Recurrence counts for one learned lesson's error signature."""

    signature: str
    error_code: str
    recorded_ts: float
    before: int
    after: int

    @property
    def holding(self) -> bool:
        """True when the signature never recurred after the lesson was recorded."""
        return self.after == 0


@dataclass(frozen=True)
class LessonsStats:
    """Workspace-wide lessons effectiveness summary."""

    lessons: list[LessonStat]
    runs_scanned: int
    runs_with_errors: int
    repair_successes: int
    top_signatures: list[tuple[str, int]]


# ---------------------------------------------------------------------------
# Run directory access
# ---------------------------------------------------------------------------


def runs_root(workspace_root: Path) -> Path:
    return Path(workspace_root) / ".local-codex-lite" / "runs"


def list_run_dirs(workspace_root: Path, limit: int | None = None) -> list[Path]:
    """Run directories of *workspace_root*, newest first (by sortable dir name)."""
    root = runs_root(workspace_root)
    if not root.is_dir():
        return []
    dirs = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    if limit is not None:
        return dirs[:limit]
    return dirs


def load_run_events(run_dir: Path) -> list[dict[str, object]]:
    """Parse ``events.jsonl`` of *run_dir*; broken or non-dict lines are skipped."""
    path = Path(run_dir) / "events.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    events: list[dict[str, object]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def _excerpt(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return int(value)
    return default


# ---------------------------------------------------------------------------
# Attempt timeline
# ---------------------------------------------------------------------------


def _code_and_detail(item: dict[str, object]) -> tuple[str, str]:
    """Extract ``(error_code, detail)`` from an issue/failure JSON document.

    Handles both shapes the runner writes: ``{"patch_error": {...}, "detail" |
    "stderr" | "errors": ...}`` (validation/apply/smoke issues) and
    ``{"issue_type": ..., "error": ...}`` (patch-generation failures).
    """
    patch_error = item.get("patch_error")
    code = ""
    if isinstance(patch_error, dict):
        code = str(patch_error.get("code") or "")
    if not code:
        code = str(item.get("issue_type") or "")
    detail = str(item.get("detail") or item.get("stderr") or item.get("error") or "")
    if not detail:
        errors = item.get("errors")
        if isinstance(errors, list):
            detail = "\n".join(str(error) for error in errors)
    if not detail and isinstance(patch_error, dict):
        detail = str(patch_error.get("detail") or "")
    return code, detail


def _issue_detail_by_code(run_dir: Path) -> dict[str, str]:
    """Map error codes to details from ``*_issue.json`` / ``failure.json``."""
    mapping: dict[str, str] = {}
    candidates = [*sorted(run_dir.glob("*_issue.json")), run_dir / "failure.json"]
    for path in candidates:
        item = _read_json(path)
        if not isinstance(item, dict):
            continue
        code, detail = _code_and_detail(item)
        if code and detail and code not in mapping:
            mapping[code] = detail
    return mapping


def _task_excerpt(run_dir: Path) -> str:
    try:
        text = (run_dir / "task.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    return _excerpt(text, _TASK_EXCERPT_CHARS)


def _final_status(run_dir: Path) -> str:
    """Collapse ``result.json`` / ``failure.json`` into one outcome word."""
    result = _read_json(run_dir / "result.json")
    if not isinstance(result, dict):
        result = {}
    if result.get("failure") or isinstance(_read_json(run_dir / "failure.json"), dict):
        return "failed"
    if result.get("applied") is True:
        return "applied"
    if result.get("dry_run"):
        return "preview"
    if result:
        return "partial"
    return "unknown"


def build_attempt_timeline(run_dir: Path) -> RunReport:
    """Build the attempt timeline for one run directory.

    Rows come from ``events.jsonl``; failed rows whose event carries no detail
    text are enriched from the matching ``*_issue.json`` / ``failure.json``
    document (matched by error code).  ``repair_count`` counts the patch
    pipeline's failed attempts (``patch_error`` events) -- for an ``applied``
    run that is exactly the number of repairs the model needed.
    """
    run_dir = Path(run_dir)
    events = load_run_events(run_dir)
    issue_details = _issue_detail_by_code(run_dir)
    rows: list[TimelineRow] = []
    repair_count = 0
    for event in events:
        stage = str(event.get("stage") or "?")
        attempt = _as_int(event.get("attempt"), _as_int(event.get("repair_attempt"), 1))
        status_raw = str(event.get("status") or "")
        if status_raw == "success":
            rows.append(TimelineRow(stage=stage, attempt=attempt, status="ok"))
            continue
        if status_raw == "patch_error":
            repair_count += 1
            error_code = str(event.get("patch_error_code") or "") or None
            detail = str(event.get("raw_error") or event.get("detail") or "")
        else:
            error_code = str(event.get("issue_type") or "") or None
            detail = str(event.get("error") or "")
        if not detail and error_code:
            detail = issue_details.get(error_code, "")
        rows.append(
            TimelineRow(
                stage=stage,
                attempt=attempt,
                status=status_raw or "unknown",
                error_code=error_code,
                detail_excerpt=_excerpt(detail, _DETAIL_EXCERPT_CHARS) or None,
            )
        )
    return RunReport(
        run_id=run_dir.name,
        task_excerpt=_task_excerpt(run_dir),
        rows=rows,
        final_status=_final_status(run_dir),
        repair_count=repair_count,
    )


def render_timeline(report: RunReport) -> str:
    """Render *report* as compact plain text (no rich markup)."""
    lines = [f"run: {report.run_id}"]
    if report.task_excerpt:
        lines.append(f"task: {report.task_excerpt}")
    if not report.rows:
        lines.append("(no events recorded)")
    for row in report.rows:
        if row.status == "ok":
            lines.append(f"{row.stage} #{row.attempt} ok")
            continue
        code = row.error_code or row.status
        suffix = f": {row.detail_excerpt}" if row.detail_excerpt else ""
        lines.append(f"{row.stage} #{row.attempt} FAILED {code}{suffix}")
    final = f"result: {report.final_status}"
    if report.repair_count:
        noun = "repair" if report.repair_count == 1 else "repairs"
        final += f" after {report.repair_count} {noun}"
    lines.append(final)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lessons effectiveness
# ---------------------------------------------------------------------------


def _run_timestamp(run_dir: Path) -> float:
    """Epoch timestamp of a run, parsed from its ``YYYYMMDD-HHMMSS...`` name.

    Per-event timestamps are unreliable (``patch_error`` events carry none), so
    the run's start time stands in for every error inside it.  Falls back to
    the directory mtime when the name does not parse.
    """
    name = Path(run_dir).name
    try:
        return datetime.strptime(name[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC).timestamp()
    except ValueError:
        pass
    try:
        return Path(run_dir).stat().st_mtime
    except OSError:
        return 0.0


def _error_signatures(events: list[dict[str, object]], run_dir: Path) -> set[str]:
    """Normalized error signatures observed in one run (events + issue files).

    ``events.jsonl`` stores sanitized (whitespace-collapsed) error text while
    ``*_issue.json`` keeps the raw multi-line detail -- the same text
    ``record_lesson`` saw -- so both sources are folded in and de-duplicated.
    """
    signatures: set[str] = set()
    for event in events:
        status = str(event.get("status") or "")
        if status not in _FAILURE_STATUSES:
            continue
        detail = str(event.get("raw_error") or event.get("error") or event.get("detail") or "")
        signature = signature_for_detail(detail)
        if signature:
            signatures.add(signature)
    for path in sorted(run_dir.glob("*_issue.json")):
        item = _read_json(path)
        if not isinstance(item, dict):
            continue
        _, detail = _code_and_detail(item)
        signature = signature_for_detail(detail)
        if signature:
            signatures.add(signature)
    return signatures


def lessons_stats(workspace_root: Path) -> LessonsStats:
    """Cross-reference ``lessons.jsonl`` with every run's recorded errors.

    For each learned lesson: ``before`` counts the runs (started) at or before
    the lesson's timestamp where its signature occurred -- this includes the
    failure that produced the lesson -- and ``after`` counts later runs where
    the same signature came back.  ``after == 0`` means the lesson is holding.
    A signature is counted at most once per run.
    """
    occurrences: list[tuple[float, str]] = []
    runs_with_errors = 0
    repair_successes = 0
    counter: Counter[str] = Counter()
    run_dirs = list_run_dirs(workspace_root)
    for run_dir in run_dirs:
        events = load_run_events(run_dir)
        signatures = _error_signatures(events, run_dir)
        ts = _run_timestamp(run_dir)
        if signatures:
            runs_with_errors += 1
        for signature in signatures:
            occurrences.append((ts, signature))
            counter[signature] += 1
        result = _read_json(run_dir / "result.json")
        had_patch_error = any(str(event.get("status") or "") == "patch_error" for event in events)
        if isinstance(result, dict) and result.get("applied") is True and had_patch_error:
            repair_successes += 1
    stats: list[LessonStat] = []
    for lesson in load_learned(workspace_root, limit=-1):
        before = sum(1 for ts, sig in occurrences if sig == lesson.signature and ts <= lesson.ts)
        after = sum(1 for ts, sig in occurrences if sig == lesson.signature and ts > lesson.ts)
        stats.append(
            LessonStat(
                signature=lesson.signature,
                error_code=lesson.error_code,
                recorded_ts=lesson.ts,
                before=before,
                after=after,
            )
        )
    return LessonsStats(
        lessons=stats,
        runs_scanned=len(run_dirs),
        runs_with_errors=runs_with_errors,
        repair_successes=repair_successes,
        top_signatures=counter.most_common(_TOP_SIGNATURES),
    )


def render_lessons_stats(stats: LessonsStats) -> str:
    """Render *stats* as a plain-text table with a summary footer."""
    lines: list[str] = []
    if not stats.lessons:
        lines.append("No learned lessons recorded yet.")
    else:
        width = max(
            len("signature"),
            max(min(len(item.signature), _SIGNATURE_RENDER_CHARS) for item in stats.lessons),
        )
        lines.append(f"{'signature'.ljust(width)}  before  after  verdict")
        for item in stats.lessons:
            signature = _excerpt(item.signature, _SIGNATURE_RENDER_CHARS).ljust(width)
            verdict = "✓ holding" if item.holding else "✗ recurring"
            lines.append(f"{signature}  {item.before:>6}  {item.after:>5}  {verdict}")
    lines.append("")
    lines.append(
        f"lessons: {len(stats.lessons)} | runs scanned: {stats.runs_scanned} | "
        f"runs with errors: {stats.runs_with_errors} | "
        f"repair successes: {stats.repair_successes}"
    )
    if stats.top_signatures:
        lines.append("top recurring signatures:")
        for signature, count in stats.top_signatures:
            lines.append(f"  {count}x {_excerpt(signature, _SIGNATURE_RENDER_CHARS)}")
    return "\n".join(lines)

from __future__ import annotations

import json
import re
import secrets
from collections import deque
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Patterns that pair a secret-bearing key/header with its value so the value
# itself can be replaced (not just prefixed) with <redacted>.
_KEY_VALUE_REDACTORS: tuple[re.Pattern[str], ...] = (
    # token=..., password=..., access_token=..., api_key=..., secret=..., ...
    re.compile(
        r"(\b(?:token|password|access_token|private_token|api_key|secret|credential)\b\s*[:=]\s*)"
        r"\S+",
        re.IGNORECASE,
    ),
    # Authorization: Bearer <...>, Authorization: Basic <...>
    re.compile(r"(\bauthorization\s*:\s*(?:bearer|basic|token)\s+)\S+", re.IGNORECASE),
    # X-Api-Key: <...>, X-Auth-Token: <...>
    re.compile(r"(\bx-(?:api-key|auth-token)\s*:\s*)\S+", re.IGNORECASE),
    # Url-embedded basic auth: https://user:token@host/...
    re.compile(r"(https?://)[^/\s@]+:[^/\s@]+@", re.IGNORECASE),
)


def sanitize_log_text(value: str, limit: int = 600) -> str:
    """Compact and redact *value* before it is persisted in logs.

    - Collapses CR/LF and runs of whitespace into single spaces.
    - Replaces the secret value following well-known credential keys/headers
      (``token=``, ``password=``, ``Authorization: Basic ...`` ...) with
      ``<redacted>``.  Unlike the prior implementation this masks the actual
      secret, not just prefixes it.
    - Trims the result to ``limit`` characters with an ellipsis suffix.
    """
    if not value:
        return ""
    compact = " ".join(value.replace("\r", "\n").split())
    for pattern in _KEY_VALUE_REDACTORS:
        if pattern.pattern.startswith("(https?://)"):
            compact = pattern.sub(r"\1<redacted>:<redacted>@", compact)
        else:
            compact = pattern.sub(r"\1<redacted>", compact)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def utc_timestamp() -> str:
    """Return a per-run timestamp that is collision-resistant within the
    same second.  The format is ``YYYYMMDD-HHMMSS-uuuuuu-xxxxxx`` where
    ``uuuuuu`` is the UTC microsecond component and ``xxxxxx`` is a 6-char
    hex suffix.  The format is still lexicographically sortable, so
    ``latest_session_dir`` keeps working and existing run directories with
    the shorter ``YYYYMMDD-HHMMSS`` shape still compare correctly.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(3)


def session_dir(workspace_root: Path, run_id: str | None = None) -> Path:
    root = workspace_root / ".local-codex-lite" / "runs"
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / (run_id or utc_timestamp())
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def latest_session_dir(workspace_root: Path) -> Path | None:
    root = workspace_root / ".local-codex-lite" / "runs"
    if not root.exists():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.name)


def latest_events_path(workspace_root: Path) -> Path | None:
    run_dir = latest_session_dir(workspace_root)
    if run_dir is None:
        return None
    path = run_dir / "events.jsonl"
    return path if path.exists() else None


def resolve_run_dir(workspace_root: Path, run_ref: str | None) -> Path | None:
    if run_ref is None or run_ref == "latest":
        return latest_session_dir(workspace_root)
    candidate = Path(run_ref)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    run_root = workspace_root / ".local-codex-lite" / "runs"
    nested = run_root / run_ref
    if nested.exists():
        return nested
    if candidate.exists():
        return candidate
    return None


def tail_events_text(path: Path, *, lines: int = 40) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8") as handle:
        tail = deque(handle, maxlen=max(1, lines))
    return "".join(tail)


def run_summary(run_dir: Path) -> dict[str, Any]:
    task = _read_text_if_exists(run_dir / "task.txt")
    result = _read_json_if_exists(run_dir / "result.json") or {}
    plan = _read_json_if_exists(run_dir / "plan.json") or {}
    evidence_dir = run_dir / "evidence"
    evidence_status = _read_json_if_exists(evidence_dir / "status.json") or {}
    evidence_metadata = _read_json_if_exists(evidence_dir / "metadata.json") or {}
    selected = _read_json_if_exists(evidence_dir / "summaries" / "selected_files.json")
    if selected is None:
        selected = _read_json_if_exists(evidence_dir / "selected_files.json") or []
    artifacts = _collect_artifacts(run_dir)
    patch_error = result.get("patch_error")
    patch_error_code = None
    if isinstance(patch_error, dict):
        patch_error_code = patch_error.get("code")
    elif hasattr(patch_error, "code"):
        patch_error_code = getattr(patch_error, "code", None)
    status = "unknown"
    if result.get("failure"):
        status = "failed"
    elif result.get("applied"):
        status = "applied"
    elif result.get("dry_run"):
        status = "dry_run"
    elif result:
        status = "ok"
    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "task": task,
        "status": status,
        "selected_files_count": len(selected) if isinstance(selected, list) else 0,
        "patch_path": str(run_dir / "patch.diff") if (run_dir / "patch.diff").exists() else None,
        "evidence_path": str(evidence_dir) if evidence_dir.exists() else None,
        "patch_error_code": patch_error_code,
        "plan_summary": plan.get("summary"),
        "result": result,
        "evidence_status": evidence_status,
        "evidence_metadata": evidence_metadata,
        "artifacts": artifacts,
    }


def dump_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_jsonable(data), ensure_ascii=False))
        handle.write("\n")


def _jsonable(data: Any) -> Any:
    if is_dataclass(data):
        return _jsonable(asdict(data))
    if isinstance(data, dict):
        return {str(key): _jsonable(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_jsonable(value) for value in data]
    if isinstance(data, tuple):
        return [_jsonable(value) for value in data]
    return data


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _collect_artifacts(run_dir: Path) -> list[str]:
    if not run_dir.exists():
        return []
    artifacts = [path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()]
    return sorted(artifacts)

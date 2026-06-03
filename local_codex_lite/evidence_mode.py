from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .evidence import save_json_file


@dataclass(frozen=True)
class EvidenceBundle:
    run_id: str
    bundle_dir: Path
    raw_dir: Path
    summaries_dir: Path
    reports_dir: Path
    metadata_path: Path
    status_path: Path


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_evidence_bundle(
    run_root: Path, *, source: str, task: str, run_id: str | None = None
) -> EvidenceBundle:
    bundle_dir = run_root / "evidence"
    raw_dir = bundle_dir / "raw"
    summaries_dir = bundle_dir / "summaries"
    reports_dir = bundle_dir / "reports"
    for path in (bundle_dir, raw_dir, summaries_dir, reports_dir):
        path.mkdir(parents=True, exist_ok=True)
    bundle = EvidenceBundle(
        run_id=run_id or run_root.name,
        bundle_dir=bundle_dir,
        raw_dir=raw_dir,
        summaries_dir=summaries_dir,
        reports_dir=reports_dir,
        metadata_path=bundle_dir / "metadata.json",
        status_path=bundle_dir / "status.json",
    )
    write_metadata(bundle, source=source, task=task)
    write_status(
        bundle,
        status="partial",
        error_code=None,
        message="evidence bundle created",
        evidence_complete=False,
    )
    return bundle


def write_metadata(bundle: EvidenceBundle, *, source: str, task: str) -> Path:
    payload = {
        "kind": "evidence_bundle",
        "created_at": utc_now_iso(),
        "source": source,
        "task": task,
        "run_id": bundle.run_id,
        "raw_artifacts": [],
        "summary_artifacts": [],
        "report_artifacts": [],
    }
    return save_json_file(bundle.metadata_path, payload)


def write_status(
    bundle: EvidenceBundle,
    *,
    status: str,
    error_code: str | None,
    message: str,
    evidence_complete: bool,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "status": status,
        "error_code": error_code,
        "message": message,
        "evidence_complete": evidence_complete,
        "updated_at": utc_now_iso(),
    }
    if extra:
        payload.update(extra)
    return save_json_file(bundle.status_path, payload)


def save_raw_text(bundle: EvidenceBundle, name: str, text: str) -> Path:
    return _save_text_artifact(bundle, bundle.raw_dir, "raw_artifacts", name, text)


def save_raw_json(bundle: EvidenceBundle, name: str, data: Any) -> Path:
    return _save_json_artifact(bundle, bundle.raw_dir, "raw_artifacts", name, data)


def save_summary_text(bundle: EvidenceBundle, name: str, text: str) -> Path:
    return _save_text_artifact(bundle, bundle.summaries_dir, "summary_artifacts", name, text)


def save_summary_json(bundle: EvidenceBundle, name: str, data: Any) -> Path:
    return _save_json_artifact(bundle, bundle.summaries_dir, "summary_artifacts", name, data)


def save_report_text(bundle: EvidenceBundle, name: str, text: str) -> Path:
    return _save_text_artifact(bundle, bundle.reports_dir, "report_artifacts", name, text)


def save_report_json(bundle: EvidenceBundle, name: str, data: Any) -> Path:
    return _save_json_artifact(bundle, bundle.reports_dir, "report_artifacts", name, data)


def list_evidence_artifacts(bundle_dir: Path) -> list[str]:
    if not bundle_dir.exists():
        return []
    files = [
        path.relative_to(bundle_dir).as_posix() for path in bundle_dir.rglob("*") if path.is_file()
    ]
    return sorted(files)


def _save_text_artifact(
    bundle: EvidenceBundle, base: Path, metadata_key: str, name: str, text: str
) -> Path:
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _record_artifact(bundle, metadata_key, path)
    return path


def _save_json_artifact(
    bundle: EvidenceBundle, base: Path, metadata_key: str, name: str, data: Any
) -> Path:
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json_file(path, data)
    _record_artifact(bundle, metadata_key, path)
    return path


def _record_artifact(bundle: EvidenceBundle, metadata_key: str, path: Path) -> None:
    if not bundle.metadata_path.exists():
        return
    metadata = _load_json(bundle.metadata_path)
    artifacts = metadata.get(metadata_key, [])
    rel = path.relative_to(bundle.bundle_dir).as_posix()
    if rel not in artifacts:
        artifacts.append(rel)
    metadata[metadata_key] = artifacts
    save_json_file(bundle.metadata_path, metadata)


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

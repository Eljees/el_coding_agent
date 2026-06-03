from __future__ import annotations

from pathlib import Path

from local_codex_lite.evidence_mode import (
    create_evidence_bundle,
    list_evidence_artifacts,
    save_raw_json,
    save_raw_text,
    save_report_text,
    save_summary_json,
)


def test_create_evidence_bundle_creates_structure(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / "20260501-010101"
    bundle = create_evidence_bundle(
        run_root, source="trufflehog", task="scan repo", run_id="20260501-010101"
    )

    assert bundle.metadata_path.exists()
    assert bundle.status_path.exists()
    assert bundle.raw_dir.exists()
    assert bundle.summaries_dir.exists()
    assert bundle.reports_dir.exists()

    save_raw_text(bundle, "raw.txt", "raw evidence")
    save_raw_json(bundle, "manifest.json", {"ok": True})
    save_summary_json(bundle, "summary.json", {"status": "ok"})
    save_report_text(bundle, "report.md", "# report")

    artifacts = list_evidence_artifacts(bundle.bundle_dir)
    assert "metadata.json" in artifacts
    assert "status.json" in artifacts
    assert "raw/raw.txt" in artifacts
    assert "raw/manifest.json" in artifacts
    assert "summaries/summary.json" in artifacts
    assert "reports/report.md" in artifacts

    metadata = bundle.metadata_path.read_text(encoding="utf-8")
    assert "raw/raw.txt" in metadata
    assert "summaries/summary.json" in metadata
    assert "reports/report.md" in metadata

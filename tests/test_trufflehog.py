from __future__ import annotations

from pathlib import Path

from local_codex_lite.trufflehog import analyze_output_root, scan_repo_urls


def test_analyze_output_root_reads_baseline_dir(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "repo-a.json").write_text(
        '{"repo": "repo-a", "findings": 2, "detectors": {"AWSKey": 2}}',
        encoding="utf-8",
    )
    (baseline / "baseline_total.json").write_text(
        '{"findings": 2, "verified": 0, "unknown": 0, "unverified": 2, "repos": 1, "failures": 0}',
        encoding="utf-8",
    )
    (baseline / "manifest.json").write_text(
        '{"timestamp": "t", "image": "img", "urls": ["u"]}', encoding="utf-8"
    )
    (baseline / "baseline_summary.csv").write_text(
        "repo,url,findings,verified,unknown,unverified,clone_status,scan_status,top_detectors\n"
        "repo-a,u,2,0,0,2,ok,ok,{'AWSKey': 2}\n",
        encoding="utf-8",
    )

    report = analyze_output_root(tmp_path)

    assert report["total"]["findings"] == 2
    assert report["same_repo_count"] == 1
    assert report["detector_totals"]["AWSKey"] == 2


def test_scan_repo_urls_writes_evidence(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_clone(url: str, dst: Path, user: str, token: str, depth: int) -> None:
        calls.append(("clone", url))
        dst.mkdir(parents=True, exist_ok=True)

    def fake_scan(
        repo_dir: Path, image: str = "trufflesecurity/trufflehog:3.94.1"
    ) -> dict[str, object]:
        calls.append(("scan", repo_dir.name))
        return {
            "findings": 1,
            "verified": 1,
            "unknown": 0,
            "unverified": 0,
            "detectors": {"AWSKey": 1},
            "raw_findings": [],
        }

    monkeypatch.setattr("local_codex_lite.trufflehog.clone_repo", fake_clone)
    monkeypatch.setattr("local_codex_lite.trufflehog.scan_repo", fake_scan)

    result = scan_repo_urls(
        ["https://example.com/a.git"],
        git_user="user",
        git_token="token",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
        keep_clones=True,
    )

    assert result.total["findings"] == 1
    assert result.baseline_dir.exists()
    assert (result.baseline_dir / "a.json").exists()
    assert calls[0][0] == "clone"
    assert calls[1][0] == "scan"

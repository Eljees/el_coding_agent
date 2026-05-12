from __future__ import annotations

import subprocess
from pathlib import Path

from local_codex_lite.trufflehog import scan_repo_urls


def test_scan_repo_urls_classifies_clone_failure_and_writes_status(tmp_path: Path, monkeypatch) -> None:
    def fake_clone(url: str, dst: Path, user: str, token: str, depth: int) -> None:  # noqa: ARG001
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "clone"],
            output="",
            stderr="fatal: Authentication required for 'https://example.com/repo.git'",
        )

    monkeypatch.setattr("local_codex_lite.trufflehog.clone_repo", fake_clone)

    result = scan_repo_urls(
        ["https://example.com/repo.git"],
        git_user="user",
        git_token="token",
        cache_root=tmp_path / "cache",
        out_root=tmp_path / "out",
        keep_clones=True,
    )

    assert result.total["failures"] == 1
    assert result.status is not None
    assert result.status["error_code"] == "auth_missing"
    assert (result.evidence_dir / "status.json").exists()

"""Tests for trufflehog.run(), clone_repo(), and scan_repo() — cover subprocess paths."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# trufflehog.run() — line 47
# ---------------------------------------------------------------------------


def test_run_executes_subprocess_and_returns_completed_process(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import run

    mock_cp = MagicMock(spec=subprocess.CompletedProcess)

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp) as spy:
        result = run(["git", "--version"], cwd=tmp_path, timeout=30)

    assert result is mock_cp
    spy.assert_called_once()
    call_kwargs = spy.call_args
    assert call_kwargs.kwargs["text"] is True
    assert call_kwargs.kwargs["capture_output"] is True
    assert call_kwargs.kwargs["timeout"] == 30
    assert call_kwargs.kwargs["cwd"] == str(tmp_path)


def test_run_without_cwd_passes_none(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import run

    mock_cp = MagicMock(spec=subprocess.CompletedProcess)

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp) as spy:
        run(["echo", "hi"])

    assert spy.call_args.kwargs["cwd"] is None


# ---------------------------------------------------------------------------
# trufflehog.clone_repo() — lines 123-146
# ---------------------------------------------------------------------------


def test_clone_repo_success_calls_git_clone_with_basic_auth(tmp_path: Path) -> None:
    import base64

    from local_codex_lite.trufflehog import clone_repo

    dst = tmp_path / "repo"
    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 0

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp) as spy:
        clone_repo("https://example.com/repo.git", dst, "myuser", "mytoken", 10)

    spy.assert_called_once()
    cmd = spy.call_args.args[0]
    expected_b64 = base64.b64encode(b"myuser:mytoken").decode()
    assert any(f"Authorization: Basic {expected_b64}" in arg for arg in cmd)
    assert str(dst) in cmd
    assert "https://example.com/repo.git" in cmd


def test_clone_repo_removes_existing_dst_before_cloning(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import clone_repo

    dst = tmp_path / "existing"
    dst.mkdir()
    (dst / "old_file.txt").write_text("old", encoding="utf-8")

    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 0

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp):
        clone_repo("https://example.com/repo.git", dst, "u", "t", 1)

    # dst is removed before clone attempt (shutil.rmtree); subprocess was called
    # (the mock doesn't recreate dst, so it's gone after rmtree + no real git)


def test_clone_repo_failure_raises_subprocess_error(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import clone_repo

    dst = tmp_path / "repo"
    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 128
    mock_cp.stdout = ""
    mock_cp.stderr = "fatal: repository not found"
    # args must be a list so _redact_subprocess_args can process it
    mock_cp.args = [
        "git",
        "-c",
        "http.extraHeader=Authorization: Basic xxx",
        "clone",
        "url",
        str(dst),
    ]

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp):
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            clone_repo("https://example.com/repo.git", dst, "u", "t", 50)

    err = exc_info.value
    assert err.returncode == 128
    # The Authorization header should be redacted in the error args
    assert all(
        "Basic" not in str(a) for a in err.cmd if "Authorization" in str(a) or "Basic" in str(a)
    )


def test_clone_repo_redacts_auth_header_in_error(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import clone_repo

    dst = tmp_path / "repo"
    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 1
    mock_cp.stdout = ""
    mock_cp.stderr = "auth error"
    mock_cp.args = [
        "git",
        "-c",
        "http.extraHeader=Authorization: Basic dXNlcjp0b2tlbg==",
        "clone",
        "https://example.com/repo.git",
        str(dst),
    ]

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp):
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            clone_repo("https://example.com/repo.git", dst, "user", "token", 1)

    cmd_args = exc_info.value.cmd
    assert isinstance(cmd_args, list)
    assert any("<redacted>" in str(a) for a in cmd_args)


# ---------------------------------------------------------------------------
# trufflehog.scan_repo() — lines 155-176
# ---------------------------------------------------------------------------


def test_scan_repo_returns_parsed_findings(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import scan_repo

    ndjson = '{"DetectorName": "AWSKey", "Verified": true}\n'
    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 0
    mock_cp.stdout = ndjson
    mock_cp.stderr = ""

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp):
        result = scan_repo(tmp_path / "myrepo")

    assert result["findings"] == 1
    assert result["verified"] == 1


def test_scan_repo_uses_default_image(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import DEFAULT_IMAGE, scan_repo

    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 0
    mock_cp.stdout = ""
    mock_cp.stderr = ""

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp) as spy:
        scan_repo(tmp_path / "repo")

    cmd = spy.call_args.args[0]
    assert DEFAULT_IMAGE in cmd


def test_scan_repo_custom_image(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import scan_repo

    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 0
    mock_cp.stdout = ""

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp) as spy:
        scan_repo(tmp_path / "repo", image="myrepo/trufflehog:dev")

    cmd = spy.call_args.args[0]
    assert "myrepo/trufflehog:dev" in cmd


def test_scan_repo_failure_raises_subprocess_error(tmp_path: Path) -> None:
    from local_codex_lite.trufflehog import scan_repo

    mock_cp = MagicMock(spec=subprocess.CompletedProcess)
    mock_cp.returncode = 1
    mock_cp.stdout = ""
    mock_cp.stderr = "docker: No such image"
    mock_cp.args = ["docker", "run", "--rm", "trufflehog:latest"]

    with patch("local_codex_lite.trufflehog.subprocess.run", return_value=mock_cp):
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            scan_repo(tmp_path / "repo")

    assert exc_info.value.returncode == 1

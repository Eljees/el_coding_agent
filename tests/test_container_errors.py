from __future__ import annotations

from local_codex_lite.container_errors import classify_container_error


def test_classifies_docker_unavailable() -> None:
    issue = classify_container_error(stderr="docker: not found")
    assert issue.code == "docker_unavailable"
    assert issue.retryable is False


def test_classifies_auth_missing() -> None:
    issue = classify_container_error(
        stderr="fatal: Authentication required for 'https://example.com/repo.git'"
    )
    assert issue.code == "auth_missing"
    assert issue.retryable is True


def test_classifies_clone_failed() -> None:
    issue = classify_container_error(stage="clone", stderr="git clone failed")
    assert issue.code == "clone_failed"
    assert issue.retryable is True


def test_classifies_malformed_report() -> None:
    issue = classify_container_error(stderr="json.decoder.JSONDecodeError: Expecting value")
    assert issue.code == "malformed_report"
    assert issue.retryable is True


def test_classifies_db_snapshot_drift() -> None:
    issue = classify_container_error(expected_db_snapshot_id="a", observed_db_snapshot_id="b")
    assert issue.code == "db_snapshot_drift"
    assert issue.retryable is False


def test_unknown_fallback() -> None:
    issue = classify_container_error(stderr="some odd failure")
    assert issue.code == "unknown"
    assert issue.retryable is True

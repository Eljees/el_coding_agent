from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ContainerErrorClassification:
    code: str
    title: str
    detail: str
    retryable: bool
    suggested_action: str
    evidence_hint: str


def classify_container_error(
    *,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
    missing_artifacts: Iterable[str] | None = None,
    expected_db_snapshot_id: str | None = None,
    observed_db_snapshot_id: str | None = None,
    stage: str | None = None,
) -> ContainerErrorClassification:
    missing = [item.lower() for item in (missing_artifacts or [])]
    text = "\n".join(part for part in (stdout, stderr, " ".join(missing)) if part).lower()

    if expected_db_snapshot_id and observed_db_snapshot_id and expected_db_snapshot_id != observed_db_snapshot_id:
        return _classification(
            code="db_snapshot_drift",
            title="Database snapshot drift",
            detail=(
                f"Observed DB snapshot {observed_db_snapshot_id} does not match expected "
                f"{expected_db_snapshot_id}."
            ),
            retryable=False,
            suggested_action="Use the pinned DB snapshot or report the drift explicitly before retrying.",
            evidence_hint="Check status.json, summary.json, and the mounted DB cache snapshot.",
        )

    if _matches_any(text, ("no inventory", "no sbom", "inventory not found", "sbom not found")) or any(
        token in missing for token in ("inventory", "sbom", "status.json", "summary.json")
    ):
        return _classification(
            code="scan_no_inventory",
            title="Scan produced no inventory",
            detail="The scan completed but no SBOM or inventory artifact was produced.",
            retryable=False,
            suggested_action="Check the scan root, unpacked artifact path, and the container command inputs.",
            evidence_hint="Inspect the unpacked payload root and raw scan outputs.",
        )

    if _matches_any(
        text,
        (
            "jsondecodeerror",
            "expecting value",
            "malformed json",
            "invalid json",
            "parse error",
            "malformed report",
            "report is not valid json",
        ),
    ):
        return _classification(
            code="malformed_report",
            title="Malformed report",
            detail="The container produced output that could not be parsed as a report.",
            retryable=True,
            suggested_action="Inspect the raw stdout/stderr and regenerate the report from the same inputs.",
            evidence_hint="Save the raw report text and parse it separately from the summary layer.",
        )

    if _matches_any(
        text,
        (
            "docker: not found",
            "no such file or directory",
            "cannot find the file specified",
            "winerror 2",
            "docker executable not found",
        ),
    ):
        return _classification(
            code="docker_unavailable",
            title="Docker unavailable",
            detail="The Docker executable could not be found or launched.",
            retryable=False,
            suggested_action="Install or start Docker Desktop and rerun doctor.",
            evidence_hint="Check PATH, Docker Desktop, and the shell used to launch the container.",
        )

    if _matches_any(
        text,
        (
            "manifest unknown",
            "pull access denied",
            "repository does not exist",
            "image not found",
            "not found: manifest",
        ),
    ):
        return _classification(
            code="docker_image_missing",
            title="Docker image missing",
            detail="The requested container image could not be pulled or resolved.",
            retryable=True,
            suggested_action="Check the image tag, registry access, and whether the image exists locally.",
            evidence_hint="Capture the full docker pull / run stderr.",
        )

    if _matches_any(
        text,
        (
            "timed out",
            "timeout",
            "context deadline exceeded",
            "exceeded the allotted time",
        ),
    ) or returncode in {124, 137, -9}:
        return _classification(
            code="container_timeout",
            title="Container timeout",
            detail="The container did not finish before the configured timeout.",
            retryable=True,
            suggested_action="Increase the timeout or reduce the scan scope, then rerun.",
            evidence_hint="Review the last logs and the timeout value used by the wrapper.",
        )

    if _matches_any(
        text,
        (
            "bind source path does not exist",
            "invalid mount",
            "mount path",
            "the system cannot find the path specified",
            "path does not exist",
        ),
    ):
        return _classification(
            code="mount_path_error",
            title="Mount path error",
            detail="The container mount source or target path was invalid.",
            retryable=False,
            suggested_action="Verify the host path, the bind mount target, and the working directory.",
            evidence_hint="Check the docker command line and the mapped Windows path.",
        )

    if _matches_any(
        text,
        (
            "permission denied",
            "access is denied",
            "not permitted",
            "read-only file system",
            "operation not permitted",
        ),
    ):
        return _classification(
            code="cache_permission_error",
            title="Cache permission error",
            detail="The container could not read or write the requested cache path.",
            retryable=True,
            suggested_action="Fix the cache volume permissions or use a writable cache directory.",
            evidence_hint="Inspect the cache mount path and Docker volume ownership.",
        )

    if _matches_any(
        text,
        (
            "authentication required",
            "401",
            "403",
            "could not read username",
            "terminal prompts disabled",
            "set gitlab_user",
            "set gitlab_token",
        ),
    ):
        return _classification(
            code="auth_missing",
            title="Authentication missing",
            detail="The scan could not authenticate against the repository host.",
            retryable=True,
            suggested_action="Set GITLAB_USER and GITLAB_TOKEN, then rerun the scan.",
            evidence_hint="Inspect the clone stderr and confirm the repository URL.",
        )

    if _matches_any(text, ("git clone", "clone failed", "repository not found", "fatal: clone")) or stage == "clone":
        return _classification(
            code="clone_failed",
            title="Repository clone failed",
            detail="The repository checkout step returned a non-zero exit code.",
            retryable=True,
            suggested_action="Check the repo URL, credentials, and network access, then rerun.",
            evidence_hint="Save the clone stderr and the repository URL used by the helper.",
        )

    if _matches_any(text, ("docker run", "container", "scan", "tool execution failed")):
        return _classification(
            code="tool_execution_failed",
            title="Tool execution failed",
            detail="A containerized scan tool returned an error without a more specific classification.",
            retryable=True,
            suggested_action="Inspect the raw tool stderr and rerun after fixing the underlying issue.",
            evidence_hint="Review the raw command output and the container logs.",
        )

    return _classification(
        code="unknown",
        title="Unknown container error",
        detail="The failure did not match a known container or scan error pattern.",
        retryable=True,
        suggested_action="Inspect raw logs, status.json, and the container command output before retrying.",
        evidence_hint="Keep stdout, stderr, and the generated evidence bundle together.",
    )


def _classification(
    *,
    code: str,
    title: str,
    detail: str,
    retryable: bool,
    suggested_action: str,
    evidence_hint: str,
) -> ContainerErrorClassification:
    return ContainerErrorClassification(
        code=code,
        title=title,
        detail=detail,
        retryable=retryable,
        suggested_action=suggested_action,
        evidence_hint=evidence_hint,
    )


def _matches_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)

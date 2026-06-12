"""Additional doctor.py coverage — uncovered branches in run_doctor, run_dependency_doctor,
run_rag_doctor, and run_full_doctor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from local_codex_lite import doctor
from local_codex_lite.doctor import DependencyProbe, DoctorProbeResult


def _stub_probe(monkeypatch, result: DoctorProbeResult) -> None:
    monkeypatch.setattr(doctor, "build_doctor_probe_client", lambda llm: object())
    monkeypatch.setattr(doctor, "probe_local_llm_health", lambda client, model: result)


# ---------------------------------------------------------------------------
# run_doctor — model_ok=False → MISMATCH (lines 147-148)
# ---------------------------------------------------------------------------


def test_run_doctor_model_mismatch(monkeypatch, tmp_path: Path) -> None:
    _stub_probe(
        monkeypatch,
        DoctorProbeResult(
            endpoint_ok=True,
            latency_s=0.01,
            response_model="other-model",
            model_ok=False,
            json_ok=True,
            json_payload={"ok": True},
            error=None,
            json_error=None,
        ),
    )
    assert doctor.run_doctor(tmp_path) == 1


# ---------------------------------------------------------------------------
# run_doctor — model_ok=None → UNKNOWN (line 152)
# ---------------------------------------------------------------------------


def test_run_doctor_model_unknown(monkeypatch, tmp_path: Path) -> None:
    _stub_probe(
        monkeypatch,
        DoctorProbeResult(
            endpoint_ok=True,
            latency_s=0.01,
            response_model=None,
            model_ok=None,
            json_ok=True,
            json_payload={"ok": True},
            error=None,
            json_error=None,
        ),
    )
    assert doctor.run_doctor(tmp_path) == 0


# ---------------------------------------------------------------------------
# run_doctor — json_ok=False (endpoint up) → FAIL (lines 162-164)
# ---------------------------------------------------------------------------


def test_run_doctor_json_fail(monkeypatch, tmp_path: Path) -> None:
    _stub_probe(
        monkeypatch,
        DoctorProbeResult(
            endpoint_ok=True,
            latency_s=0.01,
            response_model="qwen25-coder-14b-awq",
            model_ok=True,
            json_ok=False,
            json_payload=None,
            error=None,
            json_error="strict JSON probe failed",
        ),
    )
    assert doctor.run_doctor(tmp_path) == 1


# ---------------------------------------------------------------------------
# run_dependency_doctor — missing required package (lines 208-209)
# ---------------------------------------------------------------------------


def test_run_dependency_doctor_missing_required_package(monkeypatch, tmp_path: Path) -> None:
    fake_probes = [
        DependencyProbe(
            name="nonexistent-pkg",
            required=True,
            installed=False,
            version=None,
            module="nonexistent_pkg",
        )
    ]
    monkeypatch.setattr(doctor, "probe_python_dependencies", lambda: fake_probes)
    assert doctor.run_dependency_doctor(tmp_path) == 1


def test_run_dependency_doctor_missing_optional_package(monkeypatch, tmp_path: Path) -> None:
    fake_probes = [
        DependencyProbe(
            name="optional-pkg",
            required=False,
            installed=False,
            version=None,
            module="optional_pkg",
        )
    ]
    monkeypatch.setattr(doctor, "probe_python_dependencies", lambda: fake_probes)
    assert doctor.run_dependency_doctor(tmp_path) == 0


# ---------------------------------------------------------------------------
# run_rag_doctor — provider unsupported → early return 1 (lines 233-236)
# ---------------------------------------------------------------------------


def test_run_rag_doctor_unsupported_provider_returns_1(tmp_path: Path) -> None:
    from local_codex_lite.rag import RagProviderError

    with patch("local_codex_lite.doctor.ensure_rag_provider_supported", side_effect=RagProviderError("bad")):
        rc = doctor.run_rag_doctor(tmp_path)
    assert rc == 1


# ---------------------------------------------------------------------------
# run_rag_doctor — store_dir outside workspace → return 1 (lines 241-245)
# ---------------------------------------------------------------------------


def test_run_rag_doctor_store_dir_outside_workspace_returns_1(tmp_path: Path) -> None:
    from local_codex_lite.rag import RagProviderError

    with patch("local_codex_lite.doctor.ensure_rag_provider_supported", return_value="keyword"):
        with patch("local_codex_lite.doctor.resolve_store_dir", side_effect=RagProviderError("outside")):
            rc = doctor.run_rag_doctor(tmp_path)
    assert rc == 1


# ---------------------------------------------------------------------------
# run_rag_doctor — fixture exception → overall_ok=False, returns 1 (lines 265-277)
# ---------------------------------------------------------------------------


def test_run_rag_doctor_fixture_exception_returns_1(tmp_path: Path) -> None:
    with patch("local_codex_lite.doctor.ensure_rag_provider_supported", return_value="keyword"):
        with patch("local_codex_lite.doctor.resolve_store_dir", return_value=tmp_path / "rag-store"):
            with patch("local_codex_lite.doctor.index_workspace", side_effect=RuntimeError("boom")):
                rc = doctor.run_rag_doctor(tmp_path)
    assert rc == 1


def test_run_rag_doctor_fixture_produces_no_results_returns_1(tmp_path: Path) -> None:
    from local_codex_lite.rag import RagIndexInfo

    fake_info = RagIndexInfo(
        provider="keyword",
        store_dir=tmp_path / "rag-store",
        index_path=tmp_path / "rag-store/index.json",
        metadata_path=tmp_path / "rag-store/metadata.json",
        status_path=tmp_path / "rag-store/status.json",
        chunk_count=0,
        file_count=0,
    )
    with patch("local_codex_lite.doctor.index_workspace", return_value=fake_info):
        with patch("local_codex_lite.doctor.query_index", return_value=[]):
            rc = doctor.run_rag_doctor(tmp_path)
    assert rc == 1


# ---------------------------------------------------------------------------
# run_full_doctor — run_doctor fails → overall_ok=False (line 321)
# ---------------------------------------------------------------------------


def test_run_full_doctor_fails_when_run_doctor_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor, "run_doctor", lambda root: 1)
    monkeypatch.setattr(doctor, "run_dependency_doctor", lambda root: 0)
    monkeypatch.setattr(doctor, "run_rag_doctor", lambda root: 0)
    assert doctor.run_full_doctor(tmp_path) == 1


# ---------------------------------------------------------------------------
# run_full_doctor — run_rag_doctor fails → overall_ok=False (line 331)
# ---------------------------------------------------------------------------


def test_run_full_doctor_fails_when_rag_doctor_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor, "run_doctor", lambda root: 0)
    monkeypatch.setattr(doctor, "run_dependency_doctor", lambda root: 0)
    monkeypatch.setattr(doctor, "run_rag_doctor", lambda root: 1)
    assert doctor.run_full_doctor(tmp_path) == 1

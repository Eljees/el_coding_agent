"""Coverage for the doctor probes and aggregator that had no direct tests:
probe_local_llm_health, run_doctor, preview_patch, run_full_doctor.

The LLM probe is driven with a fake client so no endpoint is needed; the
aggregator is tested by stubbing the section sub-doctors.
"""

from __future__ import annotations

from local_codex_lite import doctor
from local_codex_lite.doctor import DoctorProbeResult
from local_codex_lite.llm_client import LLMResponse

_GOOD = '{"ok": true, "component": "doctor"}'


class _FakeClient:
    def __init__(
        self, *, text: str = _GOOD, model: str = "qwen25-coder-14b-awq", boom: bool = False
    ):
        self._text = text
        self._model = model
        self._boom = boom

    def chat(self, messages, max_tokens=None, status_label=None) -> LLMResponse:
        if self._boom:
            raise RuntimeError("connection refused")
        return LLMResponse(text=self._text, raw={"model": self._model})


# --- probe_local_llm_health -------------------------------------------------


def test_probe_healthy() -> None:
    r = doctor.probe_local_llm_health(_FakeClient(), "qwen25-coder-14b-awq")
    assert r.endpoint_ok and r.json_ok and r.model_ok is True and r.error is None


def test_probe_endpoint_unreachable() -> None:
    r = doctor.probe_local_llm_health(_FakeClient(boom=True), "qwen25-coder-14b-awq")
    assert r.endpoint_ok is False and "connection refused" in (r.error or "")


def test_probe_model_mismatch() -> None:
    r = doctor.probe_local_llm_health(_FakeClient(model="other-model"), "qwen25-coder-14b-awq")
    assert r.endpoint_ok is True and r.model_ok is False


def test_probe_bad_json() -> None:
    r = doctor.probe_local_llm_health(_FakeClient(text="not json at all"), "qwen25-coder-14b-awq")
    assert r.endpoint_ok is True and r.json_ok is False and r.json_error


# --- run_doctor (aggregated table; probe stubbed) ---------------------------


def _stub_probe(monkeypatch, result: DoctorProbeResult) -> None:
    monkeypatch.setattr(doctor, "build_doctor_probe_client", lambda llm: object())
    monkeypatch.setattr(doctor, "probe_local_llm_health", lambda client, model: result)


def test_run_doctor_ok(monkeypatch, tmp_path) -> None:
    _stub_probe(
        monkeypatch,
        DoctorProbeResult(
            endpoint_ok=True,
            latency_s=0.01,
            response_model="qwen25-coder-14b-awq",
            model_ok=True,
            json_ok=True,
            json_payload={"ok": True},
            error=None,
            json_error=None,
        ),
    )
    assert doctor.run_doctor(tmp_path) == 0


def test_run_doctor_endpoint_down(monkeypatch, tmp_path) -> None:
    _stub_probe(
        monkeypatch,
        DoctorProbeResult(
            endpoint_ok=False,
            latency_s=0.01,
            response_model=None,
            model_ok=False,
            json_ok=False,
            json_payload=None,
            error="down",
            json_error=None,
        ),
    )
    assert doctor.run_doctor(tmp_path) == 1


# --- preview_patch ----------------------------------------------------------


def test_preview_patch_requires_git(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    try:
        doctor.preview_patch(tmp_path, "diff")
        raise AssertionError("expected RuntimeError when git is missing")
    except RuntimeError as exc:
        assert "git" in str(exc)


def test_preview_patch_rejects_garbage_diff(tmp_path) -> None:
    rc = doctor.preview_patch(tmp_path, "this is not a valid diff\n")
    assert rc != 0


def test_preview_patch_accepts_new_file_diff(tmp_path) -> None:
    diff = (
        "diff --git a/new.txt b/new.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/new.txt\n"
        "@@ -0,0 +1 @@\n"
        "+hello\n"
    )
    assert doctor.preview_patch(tmp_path, diff) == 0


# --- run_full_doctor (aggregation of sections) ------------------------------


def test_run_full_doctor_all_ok(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(doctor, "run_doctor", lambda root: 0)
    monkeypatch.setattr(doctor, "run_dependency_doctor", lambda root: 0)
    monkeypatch.setattr(doctor, "run_rag_doctor", lambda root: 0)
    assert doctor.run_full_doctor(tmp_path) == 0


def test_run_full_doctor_fails_if_any_section_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(doctor, "run_doctor", lambda root: 0)
    monkeypatch.setattr(doctor, "run_dependency_doctor", lambda root: 1)
    monkeypatch.setattr(doctor, "run_rag_doctor", lambda root: 0)
    assert doctor.run_full_doctor(tmp_path) == 1

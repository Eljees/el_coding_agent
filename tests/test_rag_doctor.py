from __future__ import annotations

from pathlib import Path

from local_codex_lite import doctor
from local_codex_lite.config import default_config


def test_run_rag_doctor_succeeds_for_keyword_provider(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg = default_config()
    monkeypatch.setattr(doctor, "load_config", lambda root: cfg)

    result = doctor.run_rag_doctor(tmp_path)

    out = capsys.readouterr().out
    assert result == 0
    assert "local-codex-lite RAG" in out
    assert "provider" in out
    assert "keyword" in out
    assert "sensitive exclusion" in out


def test_run_rag_doctor_reports_unsupported_provider(tmp_path: Path, monkeypatch, capsys) -> None:
    cfg = default_config().model_copy(deep=True)
    cfg.rag.provider = "chroma"
    monkeypatch.setattr(doctor, "load_config", lambda root: cfg)

    result = doctor.run_rag_doctor(tmp_path)

    out = capsys.readouterr().out
    assert result == 1
    assert "provider" in out
    assert "not implemented" in out

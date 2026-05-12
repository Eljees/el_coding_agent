from __future__ import annotations

from pathlib import Path

from local_codex_lite import artifact_unpack


def test_candidate_7z_paths_include_standard_windows_locations(monkeypatch) -> None:
    monkeypatch.delenv("LOCAL_CODEX_7Z", raising=False)
    monkeypatch.delenv("SEVENZIP", raising=False)
    monkeypatch.delenv("SEVEN_ZIP", raising=False)

    candidates = artifact_unpack._candidate_7z_paths()

    assert Path(r"C:\Program Files\7-Zip\7z.exe") in candidates
    assert Path(r"C:\Program Files (x86)\7-Zip\7z.exe") in candidates


def test_find_7z_prefers_explicit_env_path(monkeypatch, tmp_path: Path) -> None:
    seven_zip = tmp_path / "7z.exe"
    seven_zip.write_text("stub", encoding="utf-8")
    monkeypatch.setenv("LOCAL_CODEX_7Z", str(seven_zip))
    monkeypatch.setattr(artifact_unpack.shutil, "which", lambda name: None)

    found = artifact_unpack._find_7z()

    assert found == seven_zip

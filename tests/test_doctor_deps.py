from __future__ import annotations

from importlib import metadata
from pathlib import Path

from local_codex_lite import doctor


def test_probe_python_dependencies_marks_optional_missing(monkeypatch) -> None:
    def fake_version(name: str) -> str:
        if name in {"httpx", "pydantic", "PyYAML"}:
            return f"{name}-1.0"
        raise metadata.PackageNotFoundError(name)

    def fake_find_spec(name: str):
        return object() if name == "rich" else None

    monkeypatch.setattr(doctor.metadata, "version", fake_version)
    monkeypatch.setattr(doctor.util, "find_spec", fake_find_spec)

    probes = doctor.probe_python_dependencies()
    names = {probe.name: probe for probe in probes}

    assert names["httpx"].installed is True
    assert names["rich"].installed is True
    assert names["pytest"].installed is False
    assert names["pytest"].required is False


def test_run_dependency_doctor_reports_missing_optional(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        doctor,
        "probe_python_dependencies",
        lambda: [
            doctor.DependencyProbe(
                name="httpx", required=True, installed=True, version="1.0", module="httpx"
            ),
            doctor.DependencyProbe(
                name="rich", required=False, installed=False, version=None, module="rich"
            ),
        ],
    )

    result = doctor.run_dependency_doctor(tmp_path)

    out = capsys.readouterr().out
    assert result == 0
    assert "local-codex-lite dependencies" in out
    assert "rich" in out
    assert "OPTIONAL" in out

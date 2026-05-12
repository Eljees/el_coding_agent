from __future__ import annotations

from pathlib import Path

from local_codex_lite.config import WorkspaceConfig
from local_codex_lite.workspace import rank_workspace_files, summarize_ranked_files


def test_rank_workspace_files_prefers_explicit_filename(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("assert True", encoding="utf-8")
    config = WorkspaceConfig(root=tmp_path)

    ranked = rank_workspace_files(tmp_path, "update app.py and README.md", config)

    top_two = {item.path.relative_to(tmp_path).as_posix() for item in ranked[:2]}
    assert {"src/app.py", "README.md"} <= top_two
    assert ranked[0].reasons


def test_rank_workspace_files_prefers_tests_for_validation_task(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "doctor.py").write_text("print('doctor')", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_doctor.py").write_text("assert True", encoding="utf-8")
    config = WorkspaceConfig(root=tmp_path)

    ranked = rank_workspace_files(tmp_path, "add pytest coverage and tests for doctor", config)

    assert ranked[0].path.parts[-2] == "tests"
    assert any("tests" in reason.lower() for reason in ranked[0].reasons)


def test_rank_workspace_files_keeps_explicit_target_above_tests(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calculator.py").write_text("assert True", encoding="utf-8")
    config = WorkspaceConfig(root=tmp_path)

    ranked = rank_workspace_files(tmp_path, "add tests for calculator.py and fix calculator.py", config)

    assert ranked[0].path.relative_to(tmp_path).as_posix() == "src/calculator.py"
    assert any("target" in reason.lower() for reason in ranked[0].reasons)


def test_rank_workspace_files_excludes_noise(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignore.py").write_text("print('ignore')", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "cache.py").write_text("print('cache')", encoding="utf-8")
    config = WorkspaceConfig(root=tmp_path)

    ranked = rank_workspace_files(tmp_path, "update app.py", config)
    rels = [item.path.relative_to(tmp_path).as_posix() for item in ranked]

    assert "src/app.py" in rels
    assert all(not rel.startswith(".venv/") for rel in rels)
    assert all(not rel.startswith(".pytest_cache/") for rel in rels)


def test_summarize_ranked_files_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "workspace.py").write_text("print('workspace')", encoding="utf-8")
    config = WorkspaceConfig(root=tmp_path)

    first = summarize_ranked_files(tmp_path, "workspace ranking", config, allow_sensitive_read=False)
    second = summarize_ranked_files(tmp_path, "workspace ranking", config, allow_sensitive_read=False)

    assert [item.path for item in first] == [item.path for item in second]
    assert first[0].reasons

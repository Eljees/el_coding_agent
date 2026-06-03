from pathlib import Path

from local_codex_lite.config import WorkspaceConfig
from local_codex_lite.workspace import build_tree


def test_build_tree_respects_filters(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / "generated_projects").mkdir()
    (tmp_path / "generated_projects" / "demo.py").write_text("print('generated')", encoding="utf-8")
    (tmp_path / "scan_runs").mkdir()
    (tmp_path / "scan_runs" / "report.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignore.py").write_text("print('no')", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "README.md").write_text("cache", encoding="utf-8")
    config = WorkspaceConfig(root=tmp_path)
    tree = build_tree(tmp_path, config)
    assert "src/app.py" in tree
    assert all(not item.startswith(".venv/") for item in tree)
    assert all(not item.startswith(".pytest_cache/") for item in tree)
    assert all(not item.startswith("generated_projects/") for item in tree)
    assert all(not item.startswith("scan_runs/") for item in tree)

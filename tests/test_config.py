from pathlib import Path

from chartorganizer import config


def test_frozen_app_keeps_library_outside_rebuild_directory(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "ChartOrganizer"
    executable = project_root / "dist" / "ChartOrganizer" / "ChartOrganizer.exe"
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(executable))

    paths = config.project_paths()

    assert paths.root == project_root
    assert paths.database == project_root / "Library" / "library.sqlite3"

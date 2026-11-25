from pathlib import Path

from chartorganizer import config
from chartorganizer.models import Playlist, PlaylistEntry, Song
from chartorganizer.repository import Repository


def test_frozen_app_keeps_library_outside_rebuild_directory(tmp_path: Path, monkeypatch):
    project_root = tmp_path / "ChartOrganizer"
    executable = project_root / "dist" / "ChartOrganizer" / "ChartOrganizer.exe"
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(executable))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))

    paths = config.project_paths()

    assert paths.root == project_root
    assert paths.database == tmp_path / "local" / "ChartOrganizer" / "Library" / "library.sqlite3"


def test_library_migration_copies_and_opens_existing_playlist_data(tmp_path: Path):
    source = tmp_path / "old-library"
    repo = Repository(source / "library.sqlite3")
    song = repo.upsert_song(Song(None, "A", "Alpha", [], "A"))
    instrument = repo.instrument("Trombone")
    repo.save_playlist(Playlist(None, "Set", instrument.id, [PlaylistEntry(song.id)]))
    destination = tmp_path / "new-library"

    config.migrate_library(source, destination)

    migrated = Repository(destination / "library.sqlite3")
    assert migrated.load_playlist("Set").entries[0].song_id == song.id
    assert (source / "library.sqlite3").exists()

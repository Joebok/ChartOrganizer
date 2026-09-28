from pathlib import Path

from chartorganizer.models import Playlist, PlaylistEntry, Song
from chartorganizer.repository import Repository


def test_songs_and_playlist_round_trip(tmp_path: Path):
    repo = Repository(tmp_path / "library.sqlite3")
    song_a = repo.upsert_song(Song(None, "A", "Alpha", ["A short"], "A"))
    song_b = repo.upsert_song(Song(None, "B", "Beta", [], "B"))
    instrument = repo.instrument("Trombone")
    saved = repo.save_playlist(Playlist(None, "Practice", instrument.id, [PlaylistEntry(song_b.id), PlaylistEntry(song_a.id), PlaylistEntry(song_b.id)]))

    loaded = repo.load_playlist("Practice")
    assert saved.id == loaded.id
    assert [e.song_id for e in loaded.entries] == [song_b.id, song_a.id, song_b.id]
    assert repo.song(song_a.id).aliases == ["A short"]


def test_duplicate_playlist_requires_unique_name(tmp_path: Path):
    repo = Repository(tmp_path / "library.sqlite3")
    song = repo.upsert_song(Song(None, "A", "Alpha", [], "A"))
    instrument = repo.instrument("Trombone")
    repo.save_playlist(Playlist(None, "Practice", instrument.id, [PlaylistEntry(song.id)]))
    try:
        repo.save_playlist(Playlist(None, "Practice", instrument.id, []))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate name should be rejected")

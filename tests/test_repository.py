from pathlib import Path

from chartorganizer.models import PartSelection, Playlist, PlaylistEntry, Song
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


def test_kindle_setting_survives_save_reopen_update_and_duplicate(tmp_path: Path):
    database = tmp_path / "library.sqlite3"
    repo = Repository(database)
    song = repo.upsert_song(Song(None, "A", "Alpha", [], "A"))
    instrument = repo.instrument("Trombone")
    playlist = repo.save_playlist(Playlist(None, "Set", instrument.id, [
        PlaylistEntry(song.id), PlaylistEntry(song.id, optimize_for_kindle=False),
    ]))
    assert [entry.optimize_for_kindle for entry in playlist.entries] == [True, False]
    repo = Repository(database)
    loaded = repo.load_playlist("Set")
    assert [entry.optimize_for_kindle for entry in loaded.entries] == [True, False]
    duplicate = repo.duplicate_playlist("Set", "Copy")
    assert [entry.optimize_for_kindle for entry in duplicate.entries] == [True, False]
    loaded.entries[0].optimize_for_kindle = False
    repo.save_playlist(loaded)
    assert [entry.optimize_for_kindle for entry in repo.load_playlist("Set").entries] == [False, False]
    assert [entry.optimize_for_kindle for entry in repo.load_playlist("Copy").entries] == [True, False]


def test_deselected_overrides_remain_available_after_reopening(tmp_path: Path):
    database = tmp_path / "library.sqlite3"
    repo = Repository(database)
    song = repo.upsert_song(Song(None, "A", "Alpha", [], "A"))
    instrument = repo.instrument("Trombone")
    original = PartSelection(None, song.id, instrument.id, "A/original.pdf")
    repo.save_selections(song.id, instrument.id, [original])
    repo.add_override_part(song.id, instrument.id, "first.pdf", "Part override: first.pdf")
    repo.add_override_part(song.id, instrument.id, "second.pdf", "Song override: second.pdf")
    repo.add_override_part(song.id, instrument.id, "first.pdf", "Part override: first.pdf")
    assert len(repo.selections(song.id, instrument.id)) == 3
    repo.save_selections(song.id, instrument.id, [original])

    reopened = Repository(database)
    assert [s.source_relative_path for s in reopened.selections(song.id, instrument.id)] == ["A/original.pdf"]
    assert [p.override_path for p in reopened.override_parts(song.id, instrument.id)] == ["first.pdf", "second.pdf"]


def test_existing_override_data_migrates_into_independent_parts_once(tmp_path: Path):
    database = tmp_path / "library.sqlite3"
    repo = Repository(database)
    song = repo.upsert_song(Song(None, "A", "Alpha", [], "A"))
    instrument = repo.instrument("Trombone")
    # Recreate the records written by the original replacement-based implementation.
    repo.save_selections(song.id, instrument.id, [
        PartSelection(None, song.id, instrument.id, "A/original.pdf", page_ranges="2", override_path="part.pdf"),
        PartSelection(None, song.id, instrument.id, "A/other.pdf", override_path="disabled.pdf", override_enabled=False),
    ])
    with repo.transaction() as conn:
        conn.execute("INSERT INTO song_instrument_overrides VALUES(?,?,?)", (song.id, instrument.id, "song.pdf"))
        conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")

    migrated = Repository(database)
    selections = migrated.selections(song.id, instrument.id)
    assert [s.source_relative_path for s in selections] == [
        "A/original.pdf", "A/other.pdf", "Overrides/part.pdf", "Overrides/song.pdf",
    ]
    assert [s.override_path for s in selections] == [None, None, "part.pdf", "song.pdf"]
    assert selections[0].page_ranges == selections[2].page_ranges == "2"
    assert {p.override_path for p in migrated.override_parts(song.id, instrument.id)} == {"part.pdf", "disabled.pdf", "song.pdf"}
    migrated.save_selections(song.id, instrument.id, selections[:2])
    assert len(Repository(database).selections(song.id, instrument.id)) == 2

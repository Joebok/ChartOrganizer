import json
import os
import sqlite3
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from chartorganizer.compiler import Compiler
from chartorganizer.config import normalize_sources
from chartorganizer.errors import ValidationError
from chartorganizer.models import PartSelection, Playlist, PlaylistEntry, Song
from chartorganizer.playlist import PlaylistService
from chartorganizer.repository import Repository, SCHEMA
from chartorganizer.scanner import candidates, scan_repertoire


def make_part(root, width):
    folder = root / "Same Song"
    folder.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=700)
    writer.write(folder / "Trombone.pdf")


def test_normalizing_sources_preserves_path_capitalization(tmp_path):
    source = tmp_path / "MiXeDShortcutID" / "Concert Repertoire"
    assert str(normalize_sources(source)[0]) == str(source.absolute())
    repo = Repository(tmp_path / "library.sqlite3")
    repo.save_source_paths([source])
    assert json.loads(repo.setting("source_paths")) == [str(source.absolute())]


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive path identity")
def test_recovers_lowercased_shortcut_paths_without_changing_song_ids(tmp_path, monkeypatch):
    shortcut_id = "MiXeDShortcutID"
    parent = tmp_path / shortcut_id / "Band"
    roots = [parent / name for name in ("Active Repertoire", "Holidays", "New Works")]
    for root in roots:
        make_part(root, 300)
    repo = Repository(tmp_path / "library.sqlite3")
    repo.set_setting("source_path", str(roots[0]))
    repo.save_source_paths([str(root).lower() for root in roots])
    old = repo.upsert_song(Song(None, "Same Song", "Custom title", ["Alias"], "Same Song",
                               needs_review=True, source_root=str(roots[0]).lower()))
    instrument = repo.instrument("Trombone")
    repo.save_selections(old.id, instrument.id,
                         [PartSelection(None, old.id, instrument.id, "Same Song/Trombone.pdf")])
    selection_id = repo.selections(old.id, instrument.id)[0].id
    repo.save_playlist(Playlist(None, "Set", instrument.id, [PlaylistEntry(old.id)]))

    # Model Drive's case-sensitive shortcut ID on an otherwise case-insensitive filesystem.
    is_dir = Path.is_dir
    iterdir = Path.iterdir

    def invalid_shortcut(path):
        return any(part.lower() == shortcut_id.lower() and part != shortcut_id for part in path.parts)

    def provider_is_dir(path):
        return False if invalid_shortcut(path) else is_dir(path)

    def provider_iterdir(path):
        if invalid_shortcut(path):
            raise FileNotFoundError(str(path))
        return iterdir(path)

    monkeypatch.setattr(Path, "is_dir", provider_is_dir)
    monkeypatch.setattr(Path, "iterdir", provider_iterdir)
    recovered = repo.source_paths()
    assert [str(root) for root in recovered] == [str(root) for root in roots]
    assert repo.song(old.id).source_root == str(roots[0])
    unavailable = []
    songs = scan_repertoire(recovered, repo, unavailable)
    assert len(songs) == 3 and not unavailable
    assert repo.song(old.id).aliases == ["Alias"]
    assert repo.song(old.id).display_name == "Custom title"
    assert repo.song(old.id).needs_review
    assert repo.load_playlist("Set").entries[0].song_id == old.id
    assert repo.selections(old.id, instrument.id)[0].id == selection_id
    assert candidates(recovered, repo.song(old.id))[0].path.exists()
    assert [str(p) for p in Repository(repo.database).source_paths()] == [str(p) for p in roots]
    assert len(scan_repertoire(recovered, repo)) == 3


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive path identity")
def test_source_spelling_changes_preserve_song_identity_and_metadata(tmp_path):
    root = tmp_path / "Concert Repertoire"
    make_part(root, 300)
    repo = Repository(tmp_path / "library.sqlite3")
    song = scan_repertoire(str(root).lower(), repo)[0]
    song.aliases = ["Alias"]
    repo.upsert_song(song)
    updated = scan_repertoire(root, repo)[0]
    assert updated.id == song.id and updated.aliases == ["Alias"]
    assert updated.source_root == str(root)
    assert len(repo.songs()) == 1


def test_discovers_nested_songs_and_loose_pdfs_without_splitting_parts(tmp_path):
    root = tmp_path / "source"

    def pdf(relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=700)
        writer.write(path)

    for relative in (
        "Havana.pdf", "Halloween/Ghostbusters.pdf", "Halloween/Thriller/PDFs/Trombone.pdf",
        "Winter Holiday Repertoire/We Three Kings/PDF charts/Trombone.pdf",
        "Winter Holiday Repertoire/Winterfest Parade Medley/PDFs/Trombone.pdf",
        "Reserve Repertoire/Wellerman/PDFs/Trombone.pdf",
        "Pep Collection/Happy.pdf", "Pep Collection/Crazy Train.pdf",
        "Maggot Brain/Maggot Brain-Trombone.pdf", "Maggot Brain/Larger print/Maggot Brain-Trombone.pdf",
        "Istanbul Not Constantinople/Istanbul - old version/Trombone.pdf",
        "Istanbul Not Constantinople/Istanbul - updated/Trombone.pdf",
    ):
        pdf(relative)
    (root / "Empty Song").mkdir()
    (root / ".mscbackup").mkdir()
    repo = Repository(tmp_path / "library.sqlite3")
    songs = scan_repertoire(root, repo)
    assert {s.display_name for s in songs} == {
        "Havana", "Ghostbusters", "Thriller", "We Three Kings", "Winterfest Parade Medley",
        "Wellerman", "Happy", "Crazy Train", "Maggot Brain", "Istanbul Not Constantinople", "Empty Song",
    }
    assert next(s.pdf_count for s in songs if s.display_name == "Maggot Brain") == 2
    assert next(s.pdf_count for s in songs if s.display_name == "Istanbul Not Constantinople") == 2
    loose = next(s for s in songs if s.display_name == "Ghostbusters")
    assert loose.relative_folder == str(Path("Halloween/Ghostbusters.pdf"))
    assert candidates(root, loose)[0].path == root / "Halloween/Ghostbusters.pdf"
    assert candidates(root, loose)[0].relative_path == loose.relative_folder
    ids = {s.relative_folder: s.id for s in songs}
    assert {s.relative_folder: s.id for s in scan_repertoire(root, repo)} == ids
    instrument = repo.instrument("Trombone")
    repo.save_selections(loose.id, instrument.id, [PartSelection(None, loose.id, instrument.id, loose.relative_folder)])
    playlist = Playlist(None, "Loose PDF", instrument.id, [PlaylistEntry(loose.id, optimize_for_kindle=False)])
    assert Compiler(repo, root, tmp_path / "overrides", tmp_path / "compiled").compile(playlist, "Trombone").page_count == 1


def test_rescan_keeps_existing_song_group_and_selections(tmp_path):
    root = tmp_path / "source"
    folder = root / "Existing Song"
    folder.mkdir(parents=True)
    for name in ("Alpha.pdf", "Beta.pdf"):
        (folder / name).write_bytes(b"pdf")
    repo = Repository(tmp_path / "library.sqlite3")
    saved = repo.upsert_song(Song(None, folder.name, "Custom title", ["Alias"], folder.name,
                                 source_root=str(root)))
    songs = scan_repertoire(root, repo)
    assert len(songs) == 1 and songs[0].id == saved.id
    assert songs[0].aliases == ["Alias"] and songs[0].pdf_count == 2


def test_sources_persist_normalize_and_reject_duplicates(tmp_path):
    repo = Repository(tmp_path / "library.sqlite3")
    first, second = tmp_path / "one", tmp_path / "two"
    repo.set_setting("source_path", str(first))
    assert repo.source_paths() == normalize_sources(first)
    assert json.loads(repo.setting("source_paths")) == [str(normalize_sources(first)[0])]
    expected = repo.save_source_paths([first, second])
    assert Repository(repo.database).source_paths() == expected
    with pytest.raises(ValueError, match="already listed"):
        repo.save_source_paths([first, first / ".." / first.name])
    if os.name == "nt":
        with pytest.raises(ValueError, match="already listed"):
            repo.save_source_paths([first, str(first).upper()])
    with pytest.raises(ValueError, match="at least one"):
        repo.save_source_paths([])
    assert repo.source_paths() == expected


def test_legacy_migration_preserves_ids_and_all_references(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    root = tmp_path / "original"
    old_schema = SCHEMA.replace("relative_folder TEXT NOT NULL,", "relative_folder TEXT NOT NULL UNIQUE,")
    old_schema = old_schema.replace(" optimize_for_kindle INTEGER NOT NULL DEFAULT 1,\n", "")
    old_schema = old_schema.replace(
        "needs_review INTEGER NOT NULL DEFAULT 0, source_root TEXT NOT NULL DEFAULT '',\n UNIQUE(source_root, relative_folder)",
        "needs_review INTEGER NOT NULL DEFAULT 0",
    )
    with sqlite3.connect(database) as conn:
        conn.executescript(old_schema)
        conn.execute("INSERT INTO meta VALUES('schema_version','3')")
        conn.execute("INSERT INTO meta VALUES('source_path',?)", (str(root),))
        conn.execute("INSERT INTO songs VALUES(42,'Same Song','Custom title','Same Song',2,1)")
        conn.execute("INSERT INTO aliases VALUES(42,'Alias')")
        conn.execute("INSERT INTO instruments VALUES(10,'Trombone','[\"trombone\"]')")
        conn.execute("INSERT INTO playlists VALUES(5,'Set',10)")
        conn.execute("INSERT INTO playlist_entries VALUES(5,42,0)")
        conn.execute("INSERT INTO part_selections VALUES(9,42,10,'Same Song/Trombone.pdf',0,'1',NULL,1)")
        conn.execute("INSERT INTO override_parts VALUES(42,10,'marked.pdf','Marked','part')")
        conn.execute("INSERT INTO song_instrument_overrides VALUES(42,10,'song.pdf')")

    for _ in range(2):
        repo = Repository(database)
        assert repo.source_paths() == normalize_sources(root)
        song = repo.song(42)
        assert (song.display_name, song.aliases, song.needs_review) == ("Custom title", ["Alias"], True)
        assert song.source_root == str(normalize_sources(root)[0])
        assert repo.load_playlist("Set").entries[0].song_id == 42
        assert repo.load_playlist("Set").entries[0].optimize_for_kindle is True
        selection = repo.selections(42, 10)[0]
        assert (selection.id, selection.page_ranges, selection.source_relative_path) == (9, "1", "Same Song/Trombone.pdf")
        assert repo.override_parts(42, 10)[0].override_path == "marked.pdf"
        with repo._connect() as conn:
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
            assert conn.execute("SELECT override_path FROM song_instrument_overrides").fetchone()[0] == "song.pdf"

    make_part(root, 300)
    other = tmp_path / "other"
    make_part(other, 500)
    songs = scan_repertoire([root, other], repo)
    assert len(songs) == 2
    assert next(s for s in songs if s.source_root == str(normalize_sources(root)[0])).id == 42


def test_scan_duplicates_offline_sources_and_remove_readd(tmp_path):
    roots = [tmp_path / "one", tmp_path / "two"]
    for index, root in enumerate(roots):
        make_part(root, 300 + index * 100)
    repo = Repository(tmp_path / "library.sqlite3")
    repo.save_source_paths(roots)
    songs = scan_repertoire(roots, repo)
    assert len({s.id for s in songs}) == 2
    songs[0].aliases = ["Short"]
    repo.upsert_song(songs[0])
    ids = [s.id for s in songs]
    assert [s.id for s in scan_repertoire(roots, repo)] == ids
    assert repo.song(ids[0]).aliases == ["Short"]
    assert candidates(roots, songs[1])[0].path.parent.parent == normalize_sources(roots)[1]
    resolved, unknown, ambiguous = PlaylistService(songs).resolve("Same Song")
    assert not resolved and not unknown and len(ambiguous["Same Song"]) == 2
    instrument = repo.instrument("Trombone")
    repo.save_playlist(Playlist(None, "Set", instrument.id, [PlaylistEntry(ids[0])]))
    roots[1].rename(tmp_path / "offline")
    unavailable = []
    assert [s.id for s in scan_repertoire(roots, repo, unavailable)] == ids
    assert unavailable == [normalize_sources(roots[1])[0]]
    assert candidates(roots, songs[1]) == []
    repo.save_source_paths([roots[1]])
    assert [s.id for s in scan_repertoire([roots[1]], repo)] == [ids[1]]
    assert repo.load_playlist("Set").entries[0].song_id == ids[0]
    repo.save_source_paths(roots)
    (tmp_path / "offline").rename(roots[1])
    assert [s.id for s in scan_repertoire(roots, repo)] == ids


def test_compile_uses_each_songs_source_and_keeps_overrides(tmp_path):
    roots = [tmp_path / "one", tmp_path / "two"]
    for width, root in zip([300, 500], roots):
        make_part(root, width)
    repo = Repository(tmp_path / "library.sqlite3")
    songs = scan_repertoire(roots, repo)
    instrument = repo.instrument("Trombone")
    for song in songs:
        part = candidates(roots, song)[0]
        repo.save_selections(song.id, instrument.id, [PartSelection(None, song.id, instrument.id, part.relative_path)])
    overrides = tmp_path / "overrides"
    overrides.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=700)
    writer.write(overrides / "marked.pdf")
    repo.add_override_part(songs[1].id, instrument.id, "marked.pdf", "Marked")
    playlist = Playlist(None, "Set", instrument.id, [PlaylistEntry(s.id, optimize_for_kindle=False) for s in reversed(songs)])
    compiler = Compiler(repo, roots, overrides, tmp_path / "compiled")
    result = compiler.compile(playlist, "Trombone")
    reader = PdfReader(result.output_path)
    assert [int(p.mediabox.width) for p in reader.pages] == [500, 600, 300]
    assert len([item for item in reader.outline if isinstance(item, dict)]) == 2
    candidates(roots, songs[1])[0].path.unlink()
    with pytest.raises(ValidationError) as error:
        compiler.compile(playlist, "Trombone")
    assert str(roots[1]).casefold() in str(error.value).casefold()

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from chartorganizer.compiler import Compiler
from chartorganizer.errors import ValidationError
from chartorganizer.models import PartSelection, Playlist, PlaylistEntry, Song
from chartorganizer.overrides import OverrideService
from chartorganizer.repository import Repository


def make_pdf(path: Path, pages: int, width: int = 612) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


def test_compiles_one_pdf_in_playlist_and_part_order(tmp_path: Path):
    source = tmp_path / "source"
    (source / "Alpha").mkdir(parents=True)
    (source / "Beta").mkdir(parents=True)
    make_pdf(source / "Alpha" / "a1.pdf", 1)
    make_pdf(source / "Alpha" / "a2.pdf", 2)
    make_pdf(source / "Beta" / "b.pdf", 3)
    repo = Repository(tmp_path / "library.sqlite3")
    alpha = repo.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    beta = repo.upsert_song(Song(None, "Beta", "Beta", [], "Beta"))
    instrument = repo.instrument("Trombone")
    repo.save_selections(alpha.id, instrument.id, [PartSelection(None, alpha.id, instrument.id, "Alpha/a1.pdf"), PartSelection(None, alpha.id, instrument.id, "Alpha/a2.pdf")])
    repo.save_selections(beta.id, instrument.id, [PartSelection(None, beta.id, instrument.id, "Beta/b.pdf")])
    playlist = repo.save_playlist(Playlist(None, "Set", instrument.id, [PlaylistEntry(alpha.id), PlaylistEntry(beta.id)]))
    result = Compiler(repo, source, tmp_path / "overrides", tmp_path / "compiled").compile(playlist, "Trombone")
    assert result.page_count == 6
    assert len(PdfReader(str(result.output_path)).pages) == 6


def test_song_instrument_override_combines_multiple_pdfs_in_selection_order(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    make_pdf(first, 1)
    make_pdf(second, 2)
    repo = Repository(tmp_path / "library.sqlite3")
    song = repo.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    instrument = repo.instrument("Trombone")
    playlist = repo.save_playlist(Playlist(None, "Set", instrument.id, [PlaylistEntry(song.id)]))

    OverrideService(repo, tmp_path / "overrides").import_song_instrument_pdfs(
        song.id, instrument.id, [first, second]
    )
    result = Compiler(repo, source, tmp_path / "overrides", tmp_path / "compiled").compile(playlist, "Trombone")

    assert result.page_count == 3
    assert len(PdfReader(str(result.output_path)).pages) == 3


def test_replacing_song_override_recombines_files_at_the_existing_selection_path(tmp_path: Path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    make_pdf(first, 1)
    make_pdf(second, 2)
    repo = Repository(tmp_path / "library.sqlite3")
    song = repo.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    instrument = repo.instrument("Trombone")
    playlist = Playlist(None, "Set", instrument.id, [PlaylistEntry(song.id)])
    service = OverrideService(repo, tmp_path / "overrides")
    override_path = service.import_song_instrument_pdf(song.id, instrument.id, first)
    original_selection_path = repo.selections(song.id, instrument.id)[0].source_relative_path
    part = repo.override_parts(song.id, instrument.id)[0]

    updated = service.replace(song.id, instrument.id, part, [second, first])
    result = Compiler(repo, tmp_path / "source", tmp_path / "overrides", tmp_path / "compiled").compile(playlist, "Trombone")

    assert updated.override_path == override_path
    assert updated.label == "Song override: second.pdf + first.pdf"
    assert repo.selections(song.id, instrument.id)[0].source_relative_path == original_selection_path
    assert result.page_count == 3
    service.delete(song.id, instrument.id, updated)
    assert repo.selections(song.id, instrument.id) == []
    assert not (tmp_path / "overrides" / override_path).exists()


@pytest.mark.parametrize("kind", ["part", "song"])
@pytest.mark.parametrize("choice,expected", [
    ("original", [300, 300]),
    ("override", [500, 500, 500]),
    ("both", [300, 300, 500, 500, 500]),
    ("reversed", [500, 500, 500, 300, 300]),
    ("ranges", [500, 300]),
])
def test_originals_and_overrides_compile_as_independent_choices(tmp_path: Path, kind, choice, expected):
    source = tmp_path / "source"
    (source / "Alpha").mkdir(parents=True)
    make_pdf(source / "Alpha" / "original.pdf", 2, width=300)
    marked = tmp_path / "marked.pdf"
    make_pdf(marked, 3, width=500)
    repo = Repository(tmp_path / "library.sqlite3")
    song = repo.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    instrument = repo.instrument("Trombone")
    repo.save_selections(song.id, instrument.id, [PartSelection(None, song.id, instrument.id, "Alpha/original.pdf")])
    original = repo.selections(song.id, instrument.id)[0]
    service = OverrideService(repo, tmp_path / "overrides")
    if kind == "part":
        service.import_pdf(original, marked)
    else:
        service.import_song_instrument_pdf(song.id, instrument.id, marked)
    original, override = repo.selections(song.id, instrument.id)
    assert original.override_path is None
    if choice == "ranges":
        original.page_ranges = "2"
        override.page_ranges = "3"
    selections = {
        "original": [original], "override": [override], "both": [original, override],
        "reversed": [override, original], "ranges": [override, original],
    }[choice]
    repo.save_selections(song.id, instrument.id, selections)
    playlist = Playlist(None, "Set", instrument.id, [PlaylistEntry(song.id, optimize_for_kindle=False)])
    result = Compiler(repo, source, tmp_path / "overrides", tmp_path / "compiled").compile(playlist, "Trombone")
    assert [int(page.mediabox.width) for page in PdfReader(result.output_path).pages] == expected
    assert result.source_count == len(selections)


def test_missing_selected_override_reports_error_without_falling_back(tmp_path: Path):
    repo = Repository(tmp_path / "library.sqlite3")
    song = repo.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    instrument = repo.instrument("Trombone")
    repo.add_override_part(song.id, instrument.id, "missing.pdf", "Part override: missing.pdf")
    playlist = Playlist(None, "Set", instrument.id, [PlaylistEntry(song.id)])
    with pytest.raises(ValidationError, match="missing Overrides/missing.pdf"):
        Compiler(repo, tmp_path / "source", tmp_path / "overrides", tmp_path / "compiled").compile(playlist, "Trombone")

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from chartorganizer.compiler import Compiler
from chartorganizer.models import PartSelection, Playlist, PlaylistEntry, Song
from chartorganizer.overrides import OverrideService
from chartorganizer.repository import Repository


def make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
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

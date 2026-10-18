import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject, NumberObject, RectangleObject,
)

from chartorganizer.compiler import Compiler
from chartorganizer.errors import ValidationError
from chartorganizer.models import PartSelection, Playlist, PlaylistEntry, Song
from chartorganizer.pdf_layout import KINDLE_HEIGHT, KINDLE_WIDTH
from chartorganizer.repository import Repository


def make_chart(path, *, scanned=False, rotation=0, cropped=False, blank=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if not blank:
        contents = DecodedStreamObject()
        if scanned:
            image = DecodedStreamObject()
            image.update({NameObject("/Type"): NameObject("/XObject"),
                          NameObject("/Subtype"): NameObject("/Image"),
                          NameObject("/Width"): NumberObject(600),
                          NameObject("/Height"): NumberObject(800),
                          NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                          NameObject("/BitsPerComponent"): NumberObject(8)})
            image.set_data(b"".join(
                b"\xff" * 100 + b"\x00" * 300 + b"\xff" * 200 if 400 <= y < 600 else b"\xff" * 600
                for y in range(800)))
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): writer._add_object(image)})})
            contents.set_data(b"q 600 0 0 800 0 0 cm /Scan Do Q")
        else:
            contents.set_data(b"0 g 100 200 300 200 re f")
        page[NameObject("/Contents")] = writer._add_object(contents)
    if cropped:
        page.mediabox = RectangleObject((-50, -40, 650, 840))
        page.cropbox = RectangleObject((50, 100, 550, 700))
    page.rotate(rotation)
    writer.write(path)


def compile_chart(tmp_path, **chart_options):
    source = tmp_path / "source"
    (source / "Alpha").mkdir(parents=True)
    path = source / "Alpha" / "chart.pdf"
    make_chart(path, **chart_options)
    repo = Repository(tmp_path / "library.sqlite3")
    song = repo.upsert_song(Song(None, "Alpha", "Alpha", [], "Alpha"))
    instrument = repo.instrument("Trombone")
    repo.save_selections(song.id, instrument.id, [PartSelection(None, song.id, instrument.id, "Alpha/chart.pdf")])
    # The same source must support different choices for separate occurrences.
    playlist = Playlist(None, "Set", instrument.id, [
        PlaylistEntry(song.id), PlaylistEntry(song.id, optimize_for_kindle=False),
    ])
    compiler = Compiler(repo, source, tmp_path / "overrides", tmp_path / "compiled")
    return compiler, playlist, path


@pytest.mark.parametrize("scanned", [False, True])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
def test_kindle_crops_visible_content_and_fits_without_distortion(tmp_path, scanned, rotation, cropped):
    compiler, playlist, original = compile_chart(tmp_path, scanned=scanned, rotation=rotation, cropped=cropped)
    original_bytes = original.read_bytes()
    result = compiler.compile(playlist, "Trombone")
    reader = PdfReader(result.output_path)
    optimized, unchanged = reader.pages
    assert float(optimized.mediabox.width) == pytest.approx(KINDLE_WIDTH)
    assert float(optimized.mediabox.height) == pytest.approx(KINDLE_HEIGHT)
    assert optimized.rotation == 0
    source_page = PdfReader(original).pages[0]
    assert unchanged.mediabox == source_page.mediabox
    assert unchanged.cropbox == source_page.cropbox
    assert unchanged.rotation == source_page.rotation
    assert original.read_bytes() == original_bytes
    assert result.page_count == 2
    assert len([item for item in reader.outline if isinstance(item, dict)]) == 2
    if scanned:
        assert len(optimized.images) == 1
    else:
        assert not optimized.images  # Vector input remains vector output.

    with pdfium.PdfDocument(result.output_path) as document:
        page = document[0]
        # Fit the screen; PDFium exposes PDF page sizes as 32-bit floats.
        width, height = page.get_size()
        bitmap = page.render(scale=min(1680 / width, 1264 / height), grayscale=True)
        try:
            assert (bitmap.width, bitmap.height) == (1680, 1264)
            pixels = bytes(bitmap.buffer)
            rows = [y for y in range(bitmap.height)
                    if min(pixels[y * bitmap.stride:y * bitmap.stride + bitmap.width]) < 128]
            columns = [x for x in range(bitmap.width)
                       if any(pixels[y * bitmap.stride + x] < 128 for y in rows)]
            ink_width, ink_height = columns[-1] - columns[0] + 1, rows[-1] - rows[0] + 1
            assert ink_width / ink_height == pytest.approx(2 / 3 if rotation % 180 else 3 / 2, abs=0.01)
            assert max(ink_width / 1680, ink_height / 1264) > 0.98
            assert columns[0] > 0 and columns[-1] < 1679
            assert rows[0] > 0 and rows[-1] < 1263
            assert columns[0] == pytest.approx(1679 - columns[-1], abs=2)
            assert rows[0] == pytest.approx(1263 - rows[-1], abs=2)
        finally:
            bitmap.close()
            page.close()


def test_blank_pages_keep_their_place_and_get_kindle_dimensions(tmp_path):
    compiler, playlist, _ = compile_chart(tmp_path, blank=True)
    result = compiler.compile(playlist, "Trombone")
    pages = PdfReader(result.output_path).pages
    assert len(pages) == 2
    assert float(pages[0].mediabox.width) == pytest.approx(KINDLE_WIDTH)
    assert float(pages[0].mediabox.height) == pytest.approx(KINDLE_HEIGHT)
    assert float(pages[1].mediabox.width) == 600


def test_renderer_failure_does_not_publish_partial_output(tmp_path, monkeypatch):
    compiler, playlist, _ = compile_chart(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError("render failed")
    monkeypatch.setattr("chartorganizer.pdf_layout.add_kindle_page", fail)
    with pytest.raises(ValidationError, match="Alpha: cannot process chart.pdf .*render failed"):
        compiler.compile(playlist, "Trombone")
    assert not list(compiler.output_dir.iterdir())

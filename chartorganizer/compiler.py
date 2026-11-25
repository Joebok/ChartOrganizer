from __future__ import annotations

import re
import tempfile
import threading
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from .config import normalize_sources
from .errors import ValidationError
from .models import CompilationResult, Playlist, ProgressCallback
from .repository import Repository
from .selections import parse_page_ranges

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover - packaging/install issue
    PdfReader = PdfWriter = None

try:
    from pypdfium2 import PdfDocument
except ImportError:  # pragma: no cover - packaging/install issue
    PdfDocument = None

# PDFium calls must be serialized if multiple compilation workers overlap.
_RENDER_LOCK = threading.Lock()


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip() or "playlist"


class Compiler:
    def __init__(self, repository: Repository, source: Path | tuple[Path, ...], overrides: Path, output_dir: Path):
        self.sources = normalize_sources(source)
        self.repository, self.source, self.overrides, self.output_dir = repository, self.sources[0], Path(overrides), Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile(self, playlist: Playlist, instrument_name: str, progress: ProgressCallback | None = None, cancel=None) -> CompilationResult:
        if PdfReader is None:
            raise ValidationError("pypdf is required to compile PDFs; install requirements.txt")
        errors: list[str] = []
        sources: list[tuple[Path, list[int] | None, str, str, int, bool]] = []
        if any(entry.optimize_for_kindle for entry in playlist.entries) and PdfDocument is None:
            raise ValidationError("pypdfium2 is required for Kindle optimization; install requirements.txt")
        total = len(playlist.entries)
        for position, entry in enumerate(playlist.entries):
            song = self.repository.song(entry.song_id)
            instrument = self.repository.instrument(instrument_name)
            if not song or not instrument:
                errors.append(f"Entry {position + 1}: song or instrument is missing")
                continue
            selections = self.repository.selections(song.id, instrument.id, playlist.id if playlist.id is not None else None)
            if not selections:
                errors.append(f"{song.display_name}: no selected parts")
                continue
            for selection in selections:
                path = self._effective_path(selection)
                if not path.exists():
                    errors.append(f"{song.display_name}: missing {selection.source_relative_path} ({path})")
                    continue
                try:
                    reader = PdfReader(str(path), strict=False)
                    if reader.is_encrypted:
                        errors.append(f"{song.display_name}: encrypted PDF {path.name}")
                        continue
                    pages = parse_page_ranges(selection.page_ranges, len(reader.pages)) if selection.page_ranges else None
                except Exception as exc:
                    errors.append(f"{song.display_name}: cannot read {path.name} ({exc})")
                    continue
                sources.append((path, pages, song.display_name, Path(selection.source_relative_path).stem, position, entry.optimize_for_kindle))
            if progress:
                progress(position + 1, max(total, 1), song.display_name)
            if cancel and cancel.is_set():
                raise ValidationError("Compilation cancelled")
        if errors:
            raise ValidationError("\n".join(errors))
        if not sources:
            raise ValidationError("Playlist has no PDF sources")

        writer = PdfWriter()
        outline_parent = None
        outline_song = None
        page_total = 0
        for path, pages, song_name, part_name, occurrence, optimize in sources:
            reader = PdfReader(str(path), strict=False)
            before = len(writer.pages)
            indexes = [page - 1 for page in pages] if pages else list(range(len(reader.pages)))
            try:
                with (_RENDER_LOCK if optimize else nullcontext()), \
                        (PdfDocument(str(path)) if optimize else nullcontext()) as document:
                    for page_index in indexes:
                        if cancel and cancel.is_set():
                            raise ValidationError("Compilation cancelled")
                        if optimize:
                            from .pdf_layout import add_kindle_page

                            rendered_page = document[page_index]
                            try:
                                add_kindle_page(writer, reader.pages[page_index], rendered_page)
                            finally:
                                rendered_page.close()
                        else:
                            writer.add_page(reader.pages[page_index])
            except ValidationError:
                raise
            except Exception as exc:
                raise ValidationError(f"{song_name}: cannot process {path.name} ({exc})") from exc
            try:
                if occurrence != outline_song:
                    # A song bookmark is added once per song occurrence.
                    outline_parent = writer.add_outline_item(song_name, before)
                    outline_song = occurrence
                writer.add_outline_item(part_name, before, parent=outline_parent)
            except Exception:
                pass
            page_total += len(indexes)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.output_dir / f"{safe_filename(playlist.name)} - {safe_filename(instrument_name)} - {stamp}.pdf"
        with tempfile.NamedTemporaryFile(prefix="chartorganizer-", suffix=".pdf", dir=self.output_dir, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with temporary.open("wb") as output:
                writer.write(output)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return CompilationResult(destination, page_total, len(sources))

    def _effective_path(self, selection) -> Path:
        if selection.override_path:
            return self.overrides / selection.override_path
        song = self.repository.song(selection.song_id)
        root = Path(song.source_root) if song and song.source_root else self.source
        return root / selection.source_relative_path

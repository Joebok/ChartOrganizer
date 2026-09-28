from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path

from .errors import ValidationError
from .models import CompilationResult, Playlist, ProgressCallback
from .repository import Repository
from .selections import parse_page_ranges

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover - packaging/install issue
    PdfReader = PdfWriter = None


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip() or "playlist"


class Compiler:
    def __init__(self, repository: Repository, source: Path, overrides: Path, output_dir: Path):
        self.repository, self.source, self.overrides, self.output_dir = repository, Path(source), Path(overrides), Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile(self, playlist: Playlist, instrument_name: str, progress: ProgressCallback | None = None, cancel=None) -> CompilationResult:
        if PdfReader is None:
            raise ValidationError("pypdf is required to compile PDFs; install requirements.txt")
        errors: list[str] = []
        sources: list[tuple[Path, list[int] | None, str, str]] = []
        total = len(playlist.entries)
        for position, entry in enumerate(playlist.entries):
            song = self.repository.song(entry.song_id)
            instrument = self.repository.instrument(instrument_name)
            if not song or not instrument:
                errors.append(f"Entry {position + 1}: song or instrument is missing")
                continue
            whole_song_override = self.repository.song_instrument_override(song.id, instrument.id)
            if whole_song_override:
                override_path = self.overrides / whole_song_override
                if not override_path.exists():
                    errors.append(f"{song.display_name}: missing song/instrument override {whole_song_override}")
                else:
                    try:
                        reader = PdfReader(str(override_path), strict=False)
                        if reader.is_encrypted:
                            errors.append(f"{song.display_name}: encrypted PDF {override_path.name}")
                        else:
                            sources.append((override_path, None, song.display_name, override_path.stem))
                    except Exception as exc:
                        errors.append(f"{song.display_name}: cannot read {override_path.name} ({exc})")
                if progress:
                    progress(position + 1, max(total, 1), song.display_name)
                if cancel and cancel.is_set():
                    raise ValidationError("Compilation cancelled")
                continue
            selections = self.repository.selections(song.id, instrument.id)
            if not selections:
                errors.append(f"{song.display_name}: no selected parts")
                continue
            for selection in selections:
                path = self._effective_path(selection)
                if not path.exists():
                    errors.append(f"{song.display_name}: missing {selection.source_relative_path}")
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
                sources.append((path, pages, song.display_name, Path(selection.source_relative_path).stem))
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
        for path, pages, song_name, part_name in sources:
            reader = PdfReader(str(path), strict=False)
            before = len(writer.pages)
            indexes = pages or list(range(len(reader.pages)))
            for page_index in indexes:
                writer.add_page(reader.pages[page_index - 1] if pages else reader.pages[page_index])
            try:
                if song_name != outline_song:
                    # A song bookmark is added once per song occurrence.
                    outline_parent = writer.add_outline_item(song_name, before)
                    outline_song = song_name
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
        if selection.override_path and selection.override_enabled:
            candidate = self.overrides / selection.override_path
            if candidate.exists():
                return candidate
        return self.source / selection.source_relative_path

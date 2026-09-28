from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import PartSelection
from .repository import Repository


class OverrideService:
    def __init__(self, repository: Repository, override_dir: Path):
        self.repository, self.override_dir = repository, Path(override_dir)
        self.override_dir.mkdir(parents=True, exist_ok=True)

    def import_pdf(self, selection: PartSelection, path: Path) -> PartSelection:
        path = Path(path)
        digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
        destination = self.override_dir / f"{selection.song_id}_{selection.instrument_id}_{digest}_{path.name}"
        shutil.copy2(path, destination)
        selection.override_path, selection.override_enabled = destination.name, True
        self.repository.update_selection(selection)
        return selection

    def import_song_instrument_pdf(self, song_id: int, instrument_id: int, path: Path) -> str:
        return self.import_song_instrument_pdfs(song_id, instrument_id, [path])

    def import_song_instrument_pdfs(self, song_id: int, instrument_id: int, paths: list[Path]) -> str:
        paths = [Path(path) for path in paths]
        if not paths:
            raise ValueError("Select at least one PDF")

        writer = PdfWriter()
        digest = hashlib.sha1()
        for path in paths:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted:
                raise ValueError(f"Encrypted PDF: {path.name}")
            writer.append(reader)

        destination = self.override_dir / f"{song_id}_{instrument_id}_song_{digest.hexdigest()[:10]}.pdf"
        with destination.open("wb") as output:
            writer.write(output)
        self.repository.save_song_instrument_override(song_id, instrument_id, destination.name)
        return destination.name

    def set_enabled(self, selection: PartSelection, enabled: bool) -> None:
        selection.override_enabled = enabled
        self.repository.update_selection(selection)

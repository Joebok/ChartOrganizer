from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import OverridePart, PartSelection
from .repository import Repository


class OverrideService:
    def __init__(self, repository: Repository, override_dir: Path):
        self.repository, self.override_dir = repository, Path(override_dir)
        self.override_dir.mkdir(parents=True, exist_ok=True)

    def import_pdf(self, selection: PartSelection, path: Path) -> PartSelection:
        path = Path(path)
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise ValueError(f"Encrypted PDF: {path.name}")
        digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
        destination = self.override_dir / f"{selection.song_id}_{selection.instrument_id}_{digest}_{path.name}"
        if path.resolve() != destination.resolve():
            shutil.copy2(path, destination)
        return self.repository.add_override_part(selection.song_id, selection.instrument_id, destination.name,
                                                 f"Part override: {path.name}")

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
        self.repository.add_override_part(song_id, instrument_id, destination.name,
                                           "Song override: " + " + ".join(path.name for path in paths), kind="song")
        return destination.name

    def replace(self, song_id: int, instrument_id: int, part: OverridePart, paths: list[Path]) -> OverridePart:
        paths = [Path(path) for path in paths]
        if not paths:
            raise ValueError("Select at least one PDF")
        destination = self.override_dir / part.override_path
        temporary = self._temporary_path(destination)
        try:
            if part.kind == "song":
                self._write_combined_pdf(temporary, paths)
                label = "Song override: " + " + ".join(path.name for path in paths)
            else:
                if len(paths) != 1:
                    raise ValueError("A part override uses one PDF")
                reader = PdfReader(str(paths[0]), strict=False)
                if reader.is_encrypted:
                    raise ValueError(f"Encrypted PDF: {paths[0].name}")
                shutil.copy2(paths[0], temporary)
                label = f"Part override: {paths[0].name}"
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        self.repository.update_override_part(song_id, instrument_id, part.override_path, label)
        return OverridePart(part.override_path, label, part.kind)

    def delete(self, song_id: int, instrument_id: int, part: OverridePart) -> None:
        unreferenced = self.repository.delete_override_part(song_id, instrument_id, part.override_path)
        if unreferenced:
            (self.override_dir / part.override_path).unlink(missing_ok=True)

    def _write_combined_pdf(self, destination: Path, paths: list[Path]) -> None:
        writer = PdfWriter()
        for path in paths:
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted:
                raise ValueError(f"Encrypted PDF: {path.name}")
            writer.append(reader)
        with destination.open("wb") as output:
            writer.write(output)

    def _temporary_path(self, destination: Path) -> Path:
        handle, name = tempfile.mkstemp(prefix=f"{destination.stem}-", suffix=".tmp", dir=self.override_dir)
        os.close(handle)
        return Path(name)

    def set_enabled(self, selection: PartSelection, enabled: bool) -> None:
        selections = self.repository.selections(selection.song_id, selection.instrument_id)
        if enabled:
            if not any(s.source_relative_path == selection.source_relative_path for s in selections):
                selections.append(selection)
        else:
            selections = [s for s in selections if s.source_relative_path != selection.source_relative_path]
        self.repository.save_selections(selection.song_id, selection.instrument_id, selections)

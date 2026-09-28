from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

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
        path = Path(path)
        digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
        destination = self.override_dir / f"{song_id}_{instrument_id}_song_{digest}_{path.name}"
        shutil.copy2(path, destination)
        self.repository.save_song_instrument_override(song_id, instrument_id, destination.name)
        return destination.name

    def set_enabled(self, selection: PartSelection, enabled: bool) -> None:
        selection.override_enabled = enabled
        self.repository.update_selection(selection)

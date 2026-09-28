from __future__ import annotations

from pathlib import Path

from .models import PdfCandidate, Song
from .repository import Repository


def scan_repertoire(source: Path, repository: Repository) -> list[Song]:
    """Read the source tree without modifying it; existing metadata is retained."""
    source = Path(source)
    if not source.exists() or not source.is_dir():
        return repository.songs()
    found: list[Song] = []
    for folder in sorted((p for p in source.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        pdfs = {p.resolve() for p in folder.rglob("*") if p.is_file() and p.suffix.casefold() == ".pdf"}
        prior = next((s for s in repository.songs() if s.relative_folder == folder.name), None)
        song = Song(prior.id if prior else None, folder.name, prior.display_name if prior else folder.name, prior.aliases if prior else [], folder.name, len(pdfs), prior.needs_review if prior else False)
        found.append(repository.upsert_song(song))
    return found


def candidates(source: Path, song: Song) -> list[PdfCandidate]:
    folder = Path(source) / song.relative_folder
    if not folder.exists():
        return []
    result = []
    for path in sorted((p for p in folder.rglob("*") if p.is_file() and p.suffix.casefold() == ".pdf"), key=lambda p: str(p).casefold()):
        stat = path.stat()
        result.append(PdfCandidate(path, str(path.relative_to(source)), stat.st_size, stat.st_mtime_ns, path.stem))
    return result

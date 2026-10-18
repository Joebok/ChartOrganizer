from __future__ import annotations

from pathlib import Path
import re

from .config import normalize_sources, source_key
from .models import PdfCandidate, Song
from .repository import Repository


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _related_name(name: str, song: str) -> bool:
    name_key, song_key = _name_key(name), _name_key(song)
    words = re.findall(r"[a-z0-9]+", song.casefold())
    name_words = re.findall(r"[a-z0-9]+", name.casefold())
    return bool(song_key and (name_key.startswith(song_key)
                             or (words and name_words and len(words[0]) >= 4 and name_words[0] == words[0])))


def _song_paths(root: Path, known_folders: set[str], part_terms: set[str]):
    """Separate collections from song folders while preserving existing song groups."""
    asset_names = {"pdf", "pdfs", "pdfcharts", "mp3", "mp3s", "audio", "parts", "scores",
                   "current", "old", "archive", "archives", "backup", "backups"}

    def visit(folder):
        if str(folder.relative_to(root)) in known_folders:
            yield folder
            return
        children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        subfolders = [p for p in children if p.is_dir() and not p.name.startswith(".")]
        pdfs = [p for p in children if p.is_file() and p.suffix.casefold() == ".pdf"]
        has_parts = any(_related_name(p.stem, folder.name)
                        or any(term in _name_key(p.stem) for term in part_terms) for p in pdfs)
        has_assets = any(_name_key(p.name) in asset_names or _related_name(p.name, folder.name)
                         for p in subfolders)
        if has_parts or has_assets or (not subfolders and len(pdfs) <= 1):
            yield folder
            return
        # This is a collection: direct PDFs are individual songs, alongside nested song folders.
        yield from pdfs
        for child in subfolders:
            yield from visit(child)

    for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if child.is_file() and child.suffix.casefold() == ".pdf":
            yield child
        elif child.is_dir() and not child.name.startswith("."):
            yield from visit(child)


def scan_repertoire(source, repository: Repository, unavailable: list[Path] | None = None) -> list[Song]:
    """Scan configured roots, retaining cached metadata for unavailable roots."""
    roots = normalize_sources(source)
    with repository.transaction() as conn:
        conn.execute("UPDATE songs SET source_root=? WHERE source_root=''", (str(roots[0]),))
    cached = repository.songs()
    prior_by_key = {(source_key(s.source_root), s.relative_folder): s for s in cached}
    part_terms = {_name_key(term) for instrument in repository.instruments() for term in instrument.filters}
    part_terms.update({"score", "partitur"})
    part_terms.discard("")
    found: list[Song] = []
    for root in roots:
        try:
            known_folders = {s.relative_folder for s in cached if source_key(s.source_root) == source_key(root)}
            scanned = []
            for path in _song_paths(root, known_folders, part_terms):
                is_pdf = path.is_file()
                pdfs = {path} if is_pdf else {p.resolve() for p in path.rglob("*") if p.is_file() and p.suffix.casefold() == ".pdf"}
                relative = str(path.relative_to(root))
                name = path.stem if is_pdf else path.name
                prior = prior_by_key.get((source_key(root), relative))
                scanned.append(Song(prior.id if prior else None, name,
                                    prior.display_name if prior else name,
                                    list(prior.aliases) if prior else [], relative, len(pdfs),
                                    prior.needs_review if prior else False, str(root)))
        except OSError:
            if unavailable is not None:
                unavailable.append(root)
            found.extend(s for s in cached if source_key(s.source_root) == source_key(root))
            continue
        found.extend(repository.upsert_song(song) for song in scanned)
    return sorted(found, key=lambda s: (s.display_name.casefold(), s.source_root))


def candidates(source, song: Song) -> list[PdfCandidate]:
    root = Path(song.source_root) if song.source_root else normalize_sources(source)[0]
    folder = root / song.relative_folder
    if not folder.exists():
        return []
    result = []
    paths = [folder] if folder.is_file() and folder.suffix.casefold() == ".pdf" else folder.rglob("*")
    for path in sorted((p for p in paths if p.is_file() and p.suffix.casefold() == ".pdf"), key=lambda p: str(p).casefold()):
        stat = path.stat()
        result.append(PdfCandidate(path, str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns, path.stem))
    return result

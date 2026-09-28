from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Song:
    id: int | None
    folder_name: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    relative_folder: str = ""
    pdf_count: int = 0
    needs_review: bool = False


@dataclass
class Instrument:
    id: int | None
    name: str
    filters: list[str] = field(default_factory=list)


@dataclass
class PdfCandidate:
    path: Path
    relative_path: str
    size: int
    modified_ns: int
    label: str = ""


@dataclass
class PartSelection:
    id: int | None
    song_id: int
    instrument_id: int
    source_relative_path: str
    order_index: int = 0
    page_ranges: str | None = None
    override_path: str | None = None
    override_enabled: bool = True
    missing: bool = False


@dataclass
class PlaylistEntry:
    song_id: int
    position: int = 0


@dataclass
class Playlist:
    id: int | None
    name: str
    instrument_id: int
    entries: list[PlaylistEntry] = field(default_factory=list)
    dirty: bool = False


@dataclass
class CompilationResult:
    output_path: Path
    page_count: int
    source_count: int


ProgressCallback = Callable[[int, int, str], None]

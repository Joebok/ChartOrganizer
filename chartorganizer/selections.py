from __future__ import annotations

import re
from pathlib import Path

from .errors import ValidationError
from .models import PartSelection, PdfCandidate
from .repository import Repository


def parse_page_ranges(value: str, page_count: int | None = None) -> list[int]:
    pages: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", token)
        if not match:
            raise ValidationError(f"Invalid page range: {token}")
        start, end = int(match.group(1)), int(match.group(2) or match.group(1))
        if start < 1 or end < start or (page_count is not None and end > page_count):
            raise ValidationError(f"Page range outside PDF: {token}")
        pages.extend(range(start, end + 1))
    return pages


class SelectionService:
    def __init__(self, repository: Repository, source: Path):
        self.repository, self.source = repository, Path(source)

    def auto_select(self, song_id: int, instrument_id: int, candidates: list[PdfCandidate], instrument,
                    playlist_id: int | None = None) -> list[PartSelection]:
        from .matcher import match_instrument
        result = match_instrument(candidates, instrument)
        if result.ambiguous:
            return []
        selections = [PartSelection(None, song_id, instrument_id, c.relative_path, i) for i, c in enumerate(result.selected)]
        self.repository.save_selections(song_id, instrument_id, selections, playlist_id)
        return selections

    def save(self, selections: list[PartSelection]) -> None:
        if not selections:
            raise ValidationError("At least one part must be selected")
        self.repository.save_selections(selections[0].song_id, selections[0].instrument_id, selections)

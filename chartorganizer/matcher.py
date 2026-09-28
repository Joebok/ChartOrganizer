from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Instrument, PdfCandidate


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@dataclass
class MatchResult:
    selected: list[PdfCandidate]
    ambiguous: list[PdfCandidate]
    reason: str | None = None


def _part_number(path: PdfCandidate) -> int:
    match = re.search(r"(?:trombone|posaune|tbn|bone)[^0-9]*([0-9]+)", path.path.stem.casefold())
    return int(match.group(1)) if match else 0


def match_instrument(candidates: list[PdfCandidate], instrument: Instrument) -> MatchResult:
    filters = [normalize(f) for f in instrument.filters]
    matches: list[PdfCandidate] = []
    for candidate in candidates:
        name = normalize(candidate.path.stem)
        if any(token and token in name for token in filters):
            # "from tbn-bari" describes a source arrangement, not a trombone part.
            lowered = candidate.path.stem.casefold()
            if instrument.name.casefold() == "trombone" and re.search(r"from[^-]*(?:tbn|trombone)", lowered):
                continue
            matches.append(candidate)
    matches.sort(key=lambda c: (_part_number(c), str(c.path).casefold()))
    if not matches:
        return MatchResult([], [], "No individual instrument PDF found")
    parent_dirs = {str(c.path.parent).casefold() for c in matches}
    if len(parent_dirs) > 1:
        return MatchResult([], matches, "Parts appear in multiple arrangements; choose one arrangement")
    return MatchResult(matches, [], None)

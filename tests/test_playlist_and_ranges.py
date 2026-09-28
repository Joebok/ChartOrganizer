from chartorganizer.models import Playlist, Song
from chartorganizer.playlist import PlaylistService
from chartorganizer.selections import parse_page_ranges


def test_alias_resolution_preserves_order_and_repeats():
    songs = [Song(1, "Long Song", "Long Song", ["Short"], "Long Song"), Song(2, "Other", "Other", [], "Other")]
    service = PlaylistService(songs)
    resolved, unknown, ambiguous = service.resolve("Short, Other, Short")
    assert [s.id for s in resolved] == [1, 2, 1]
    assert not unknown and not ambiguous


def test_page_range_parser():
    assert parse_page_ranges("1-3, 7", 7) == [1, 2, 3, 7]

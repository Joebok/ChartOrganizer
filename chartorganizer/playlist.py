from __future__ import annotations

import re

from .models import Playlist, PlaylistEntry, Song


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


class PlaylistService:
    def __init__(self, songs: list[Song]):
        self.songs = songs
        self.index: dict[str, list[Song]] = {}
        for song in songs:
            for value in [song.display_name, song.folder_name, *song.aliases]:
                bucket = self.index.setdefault(_key(value), [])
                if not any(existing.id == song.id for existing in bucket):
                    bucket.append(song)

    def resolve(self, text: str) -> tuple[list[Song], list[str], dict[str, list[Song]]]:
        resolved: list[Song] = []
        unknown: list[str] = []
        ambiguous: dict[str, list[Song]] = {}
        for token in (p.strip() for p in text.split(",")):
            if not token:
                continue
            matches = self.index.get(_key(token), [])
            if len(matches) == 1:
                resolved.append(matches[0])
            elif not matches:
                unknown.append(token)
            else:
                ambiguous[token] = matches
        return resolved, unknown, ambiguous

    def add(self, playlist: Playlist, song: Song) -> None:
        playlist.entries.append(PlaylistEntry(song.id, len(playlist.entries)))
        playlist.dirty = True

    def remove(self, playlist: Playlist, index: int) -> None:
        if 0 <= index < len(playlist.entries):
            playlist.entries.pop(index)
            self._renumber(playlist)
            playlist.dirty = True

    def move(self, playlist: Playlist, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= index < len(playlist.entries) and 0 <= target < len(playlist.entries):
            playlist.entries[index], playlist.entries[target] = playlist.entries[target], playlist.entries[index]
            self._renumber(playlist)
            playlist.dirty = True

    @staticmethod
    def _renumber(playlist: Playlist) -> None:
        for i, entry in enumerate(playlist.entries):
            entry.position = i

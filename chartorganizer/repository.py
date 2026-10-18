from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import Instrument, OverridePart, PartSelection, Playlist, PlaylistEntry, Song
from .config import DEFAULT_SOURCE, normalize_sources, recover_source_path, source_key


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS songs (
 id INTEGER PRIMARY KEY, folder_name TEXT NOT NULL, display_name TEXT NOT NULL,
 relative_folder TEXT NOT NULL, pdf_count INTEGER NOT NULL DEFAULT 0,
 needs_review INTEGER NOT NULL DEFAULT 0, source_root TEXT NOT NULL DEFAULT '',
 UNIQUE(source_root, relative_folder)
);
CREATE TABLE IF NOT EXISTS aliases (song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
 alias TEXT NOT NULL, PRIMARY KEY(song_id, alias));
CREATE TABLE IF NOT EXISTS instruments (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, filters TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS part_selections (
 id INTEGER PRIMARY KEY, song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
 instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
 source_relative_path TEXT NOT NULL, order_index INTEGER NOT NULL,
 page_ranges TEXT, override_path TEXT, override_enabled INTEGER NOT NULL DEFAULT 1,
 UNIQUE(song_id, instrument_id, source_relative_path)
);
CREATE TABLE IF NOT EXISTS song_instrument_overrides (
 song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
 instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
 override_path TEXT NOT NULL,
 PRIMARY KEY(song_id, instrument_id)
);
CREATE TABLE IF NOT EXISTS override_parts (
 song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
 instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
 override_path TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'part',
 PRIMARY KEY(song_id, instrument_id, override_path)
);
CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
 instrument_id INTEGER NOT NULL REFERENCES instruments(id));
CREATE TABLE IF NOT EXISTS playlist_entries (playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
 song_id INTEGER NOT NULL REFERENCES songs(id), position INTEGER NOT NULL,
 optimize_for_kindle INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(playlist_id, position));
"""


class Repository:
    def __init__(self, database: Path | str):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(playlist_entries)")}
            if "optimize_for_kindle" not in columns:
                conn.execute("ALTER TABLE playlist_entries ADD COLUMN optimize_for_kindle INTEGER NOT NULL DEFAULT 1")
            conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','3')")
            version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
            if version == "1":
                for row in conn.execute("SELECT * FROM part_selections WHERE override_path IS NOT NULL").fetchall():
                    self._add_override_part(conn, row["song_id"], row["instrument_id"], row["override_path"],
                                            f"Part override: {Path(row['override_path']).name}",
                                            row["page_ranges"], bool(row["override_enabled"]))
                    conn.execute("UPDATE part_selections SET override_path=NULL,override_enabled=1 WHERE id=?", (row["id"],))
                for row in conn.execute("SELECT * FROM song_instrument_overrides").fetchall():
                    self._add_override_part(conn, row["song_id"], row["instrument_id"], row["override_path"],
                                            f"Song override: {Path(row['override_path']).name}", kind="song")
                conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
            elif version == "2":
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(override_parts)")}
                if "kind" not in columns:
                    conn.execute("ALTER TABLE override_parts ADD COLUMN kind TEXT NOT NULL DEFAULT 'part'")
                conn.execute("UPDATE override_parts SET kind='song' WHERE label LIKE 'Song override:%'")
                conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
            for name, filters in (
                ("Trombone", ["trombone", "tbn", "posaune"]),
                ("Trumpet", ["trumpet", "tpt", "trompete"]),
                ("Tuba", ["tuba", "sousaphone"]),
                ("Tenor Saxophone", ["tenor sax", "tenor_sax", "tenorsax"]),
                ("Alto Saxophone", ["alto sax", "alto_sax", "altsax"]),
                ("Baritone Horn", ["baritone horn", "baritone_horn", "euphonium"]),
                ("Horn in F", ["horn in f", "horn_in_f", "f horn"]),
                ("Flute", ["flute", "piccolo"]),
                ("Clarinet", ["clarinet", "bb clarinet"]),
                ("Baritone Saxophone", ["baritone sax", "baritone_sax", "bari sax"]),
                ("Percussion", ["percussion", "drums", "snare", "cymbals"]),
            ):
                conn.execute("INSERT OR IGNORE INTO instruments(name,filters) VALUES(?,?)", (name, json.dumps(filters)))
        self._migrate_sources()

    def _migrate_sources(self):
        with self._connect() as conn:
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(songs)")}
            if "source_root" not in columns:
                # Rebuild only the parent table, keeping all IDs and child references.
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("BEGIN")
                conn.execute("CREATE TABLE songs_new (id INTEGER PRIMARY KEY, folder_name TEXT NOT NULL, "
                             "display_name TEXT NOT NULL, relative_folder TEXT NOT NULL, "
                             "pdf_count INTEGER NOT NULL DEFAULT 0, needs_review INTEGER NOT NULL DEFAULT 0, "
                             "source_root TEXT NOT NULL DEFAULT '', UNIQUE(source_root, relative_folder))")
                saved = conn.execute("SELECT value FROM meta WHERE key='source_path'").fetchone()
                source = str(normalize_sources(saved["value"] if saved else DEFAULT_SOURCE)[0])
                conn.execute("INSERT INTO songs_new SELECT id,folder_name,display_name,relative_folder,"
                             "pdf_count,needs_review,? FROM songs", (source,))
                conn.execute("DROP TABLE songs")
                conn.execute("ALTER TABLE songs_new RENAME TO songs")
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Source migration failed library integrity check")
            conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")

    def source_paths(self, default: Path = DEFAULT_SOURCE) -> tuple[Path, ...]:
        saved = self.setting("source_paths")
        reference = normalize_sources(self.setting("source_path") or default)[0]
        sources = normalize_sources(json.loads(saved) if saved else reference)
        recovered = tuple(recover_source_path(source, reference) for source in sources)
        if not saved or [str(p) for p in recovered] != [str(p) for p in sources]:
            sources = recovered
            self.save_source_paths(sources)
        return sources

    def save_source_paths(self, sources) -> tuple[Path, ...]:
        sources = normalize_sources(sources)
        with self.transaction() as conn:
            conn.execute("INSERT INTO meta(key,value) VALUES('source_paths',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps([str(p) for p in sources]),))
            conn.execute("UPDATE songs SET source_root=? WHERE source_root=''", (str(sources[0]),))
            by_key = {source_key(p): str(p) for p in sources}
            for row in conn.execute("SELECT id,source_root FROM songs").fetchall():
                corrected = by_key.get(source_key(row["source_root"]))
                if corrected is not None and corrected != row["source_root"]:
                    conn.execute("UPDATE songs SET source_root=? WHERE id=?", (corrected, row["id"]))
        return sources

    @contextmanager
    def transaction(self):
        with self._connect() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def instruments(self) -> list[Instrument]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM instruments ORDER BY name").fetchall()
        return [Instrument(r["id"], r["name"], json.loads(r["filters"])) for r in rows]

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def instrument(self, name: str) -> Instrument | None:
        with self._connect() as conn:
            r = conn.execute("SELECT * FROM instruments WHERE lower(name)=lower(?)", (name,)).fetchone()
        return Instrument(r["id"], r["name"], json.loads(r["filters"])) if r else None

    def save_instrument(self, instrument: Instrument) -> Instrument:
        with self.transaction() as conn:
            if instrument.id:
                conn.execute("UPDATE instruments SET name=?, filters=? WHERE id=?", (instrument.name, json.dumps(instrument.filters), instrument.id))
                ident = instrument.id
            else:
                cur = conn.execute("INSERT INTO instruments(name,filters) VALUES(?,?)", (instrument.name, json.dumps(instrument.filters)))
                ident = cur.lastrowid
        return Instrument(ident, instrument.name, list(instrument.filters))

    def upsert_song(self, song: Song) -> Song:
        with self.transaction() as conn:
            source_root = str(normalize_sources(song.source_root)[0]) if song.source_root else ""
            rows = conn.execute("SELECT id,source_root FROM songs WHERE relative_folder=?", (song.relative_folder,)).fetchall()
            row = next((r for r in rows if source_key(r["source_root"]) == source_key(source_root)), None)
            if row:
                ident = row["id"]
                conn.execute("UPDATE songs SET folder_name=?,display_name=?,pdf_count=?,needs_review=?,source_root=? WHERE id=?", (song.folder_name, song.display_name, song.pdf_count, int(song.needs_review), source_root, ident))
            else:
                cur = conn.execute("INSERT INTO songs(folder_name,display_name,relative_folder,pdf_count,needs_review,source_root) VALUES(?,?,?,?,?,?)", (song.folder_name, song.display_name, song.relative_folder, song.pdf_count, int(song.needs_review), source_root))
                ident = cur.lastrowid
            conn.execute("DELETE FROM aliases WHERE song_id=?", (ident,))
            conn.executemany("INSERT INTO aliases(song_id,alias) VALUES(?,?)", [(ident, a) for a in sorted(set(song.aliases))])
        return Song(ident, song.folder_name, song.display_name, list(song.aliases), song.relative_folder, song.pdf_count, song.needs_review, source_root)

    def songs(self) -> list[Song]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM songs ORDER BY display_name COLLATE NOCASE").fetchall()
            aliases = {}
            for r in conn.execute("SELECT song_id,alias FROM aliases").fetchall():
                aliases.setdefault(r["song_id"], []).append(r["alias"])
        return [Song(r["id"], r["folder_name"], r["display_name"], aliases.get(r["id"], []), r["relative_folder"], r["pdf_count"], bool(r["needs_review"]), r["source_root"]) for r in rows]

    def song(self, song_id: int) -> Song | None:
        return next((s for s in self.songs() if s.id == song_id), None)

    def save_selections(self, song_id: int, instrument_id: int, selections: list[PartSelection]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM part_selections WHERE song_id=? AND instrument_id=?", (song_id, instrument_id))
            conn.executemany("INSERT INTO part_selections(song_id,instrument_id,source_relative_path,order_index,page_ranges,override_path,override_enabled) VALUES(?,?,?,?,?,?,?)", [(song_id, instrument_id, s.source_relative_path, i, s.page_ranges, s.override_path, int(s.override_enabled)) for i, s in enumerate(selections)])

    def selections(self, song_id: int, instrument_id: int) -> list[PartSelection]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM part_selections WHERE song_id=? AND instrument_id=? ORDER BY order_index", (song_id, instrument_id)).fetchall()
        return [PartSelection(r["id"], r["song_id"], r["instrument_id"], r["source_relative_path"], r["order_index"], r["page_ranges"], r["override_path"], bool(r["override_enabled"])) for r in rows]

    def update_selection(self, selection: PartSelection) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE part_selections SET page_ranges=?,override_path=?,override_enabled=? WHERE id=?", (selection.page_ranges, selection.override_path, int(selection.override_enabled), selection.id))

    def override_parts(self, song_id: int, instrument_id: int) -> list[OverridePart]:
        with self._connect() as conn:
            rows = conn.execute("SELECT override_path,label,kind FROM override_parts WHERE song_id=? AND instrument_id=? ORDER BY rowid", (song_id, instrument_id)).fetchall()
        return [OverridePart(r["override_path"], r["label"], r["kind"]) for r in rows]

    def add_override_part(self, song_id: int, instrument_id: int, override_path: str, label: str, kind: str = "part") -> PartSelection:
        with self.transaction() as conn:
            self._add_override_part(conn, song_id, instrument_id, override_path, label, kind=kind)
        selection_path = OverridePart(override_path, label, kind).selection_path
        return next(s for s in self.selections(song_id, instrument_id) if s.source_relative_path == selection_path)

    @staticmethod
    def _add_override_part(conn, song_id: int, instrument_id: int, override_path: str, label: str,
                           page_ranges: str | None = None, selected: bool = True, kind: str = "part") -> None:
        conn.execute("INSERT INTO override_parts(song_id,instrument_id,override_path,label,kind) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(song_id,instrument_id,override_path) DO UPDATE SET label=excluded.label,kind=excluded.kind",
                     (song_id, instrument_id, override_path, label, kind))
        if selected:
            order = conn.execute("SELECT COALESCE(MAX(order_index),-1)+1 FROM part_selections WHERE song_id=? AND instrument_id=?", (song_id, instrument_id)).fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO part_selections(song_id,instrument_id,source_relative_path,order_index,page_ranges,override_path) VALUES(?,?,?,?,?,?)",
                         (song_id, instrument_id, OverridePart(override_path, label, kind).selection_path, order, page_ranges, override_path))

    def update_override_part(self, song_id: int, instrument_id: int, override_path: str, label: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE override_parts SET label=? WHERE song_id=? AND instrument_id=? AND override_path=?",
                         (label, song_id, instrument_id, override_path))

    def delete_override_part(self, song_id: int, instrument_id: int, override_path: str) -> bool:
        with self.transaction() as conn:
            conn.execute("DELETE FROM override_parts WHERE song_id=? AND instrument_id=? AND override_path=?",
                         (song_id, instrument_id, override_path))
            conn.execute("DELETE FROM part_selections WHERE song_id=? AND instrument_id=? AND source_relative_path=?",
                         (song_id, instrument_id, OverridePart(override_path, "").selection_path))
            conn.execute("DELETE FROM song_instrument_overrides WHERE song_id=? AND instrument_id=? AND override_path=?",
                         (song_id, instrument_id, override_path))
            rows = conn.execute("SELECT id FROM part_selections WHERE song_id=? AND instrument_id=? ORDER BY order_index,id",
                                (song_id, instrument_id)).fetchall()
            for order, row in enumerate(rows):
                conn.execute("UPDATE part_selections SET order_index=? WHERE id=?", (order, row["id"]))
            referenced = conn.execute(
                "SELECT 1 FROM override_parts WHERE override_path=? UNION ALL "
                "SELECT 1 FROM part_selections WHERE override_path=? UNION ALL "
                "SELECT 1 FROM song_instrument_overrides WHERE override_path=? LIMIT 1",
                (override_path, override_path, override_path),
            ).fetchone()
        return referenced is None

    def save_playlist(self, playlist: Playlist, replace: bool = False) -> Playlist:
        with self.transaction() as conn:
            existing = conn.execute("SELECT id FROM playlists WHERE name=?", (playlist.name,)).fetchone()
            if existing and (not playlist.id or existing["id"] != playlist.id) and not replace:
                raise ValueError(f"A playlist named '{playlist.name}' already exists")
            if playlist.id:
                conn.execute("UPDATE playlists SET name=?,instrument_id=? WHERE id=?", (playlist.name, playlist.instrument_id, playlist.id))
                ident = playlist.id
            elif existing:
                ident = existing["id"]
                conn.execute("UPDATE playlists SET instrument_id=? WHERE id=?", (playlist.instrument_id, ident))
            else:
                ident = conn.execute("INSERT INTO playlists(name,instrument_id) VALUES(?,?)", (playlist.name, playlist.instrument_id)).lastrowid
            conn.execute("DELETE FROM playlist_entries WHERE playlist_id=?", (ident,))
            conn.executemany("INSERT INTO playlist_entries(playlist_id,song_id,position,optimize_for_kindle) VALUES(?,?,?,?)", [(ident, e.song_id, i, int(e.optimize_for_kindle)) for i, e in enumerate(playlist.entries)])
        return Playlist(ident, playlist.name, playlist.instrument_id, [PlaylistEntry(e.song_id, i, e.optimize_for_kindle) for i, e in enumerate(playlist.entries)], False)

    def playlists(self) -> list[str]:
        with self._connect() as conn:
            return [r["name"] for r in conn.execute("SELECT name FROM playlists ORDER BY name COLLATE NOCASE")]

    def load_playlist(self, name: str) -> Playlist | None:
        with self._connect() as conn:
            p = conn.execute("SELECT * FROM playlists WHERE name=?", (name,)).fetchone()
            if not p:
                return None
            rows = conn.execute("SELECT song_id,position,optimize_for_kindle FROM playlist_entries WHERE playlist_id=? ORDER BY position", (p["id"],)).fetchall()
        return Playlist(p["id"], p["name"], p["instrument_id"], [PlaylistEntry(r["song_id"], r["position"], bool(r["optimize_for_kindle"])) for r in rows])

    def duplicate_playlist(self, source_name: str, target_name: str) -> Playlist:
        source = self.load_playlist(source_name)
        if not source:
            raise KeyError(source_name)
        return self.save_playlist(Playlist(None, target_name, source.instrument_id, [PlaylistEntry(e.song_id, e.position, e.optimize_for_kindle) for e in source.entries]))

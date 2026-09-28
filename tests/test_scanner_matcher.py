from pathlib import Path

from chartorganizer.matcher import match_instrument
from chartorganizer.models import Instrument
from chartorganizer.repository import Repository
from chartorganizer.scanner import candidates, scan_repertoire


def test_scan_includes_empty_folders_and_nested_pdfs(tmp_path: Path):
    source = tmp_path / "source"
    (source / "Empty").mkdir(parents=True)
    nested = source / "Chameleon" / "current"
    nested.mkdir(parents=True)
    (nested / "Chameleon - Trombone 2.pdf").write_bytes(b"pdf")
    repo = Repository(tmp_path / "db.sqlite3")
    songs = scan_repertoire(source, repo)
    assert [s.display_name for s in songs] == ["Chameleon", "Empty"]
    assert len(candidates(source, songs[0])) == 1


def test_trombone_matches_posaune_and_all_numbered_parts(tmp_path: Path):
    paths = []
    for name in ("Song-Trombone_2.pdf", "Song-Posaune_(1).pdf", "Song-Horn (from tbn-bari).pdf"):
        path = tmp_path / name
        path.write_bytes(b"")
        paths.append(type("Candidate", (), {"path": path, "relative_path": name})())
    result = match_instrument(paths, Instrument(1, "Trombone", ["trombone", "posaune"]))
    assert [p.path.name for p in result.selected] == ["Song-Posaune_(1).pdf", "Song-Trombone_2.pdf"]

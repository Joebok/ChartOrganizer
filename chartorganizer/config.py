from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import os
import json
import shutil
import sqlite3


DEFAULT_SOURCE = Path.home() / "Documents" / "Sheet Music"


def source_key(source: Path | str) -> str:
    """Compare Windows paths without changing the spelling used for filesystem I/O."""
    if source == "":
        return ""
    return os.path.normcase(os.path.abspath(Path(source).expanduser()))


def normalize_sources(sources) -> tuple[Path, ...]:
    if isinstance(sources, (str, Path)):
        sources = [sources]
    result = tuple(Path(os.path.abspath(Path(p).expanduser())) for p in sources)
    if not result:
        raise ValueError("Specify at least one source folder")
    if len({source_key(p) for p in result}) != len(result):
        raise ValueError("That source folder is already listed")
    return result


def recover_source_path(source: Path, reference: Path) -> Path:
    """Recover previously lowercased paths using a known, correctly spelled root."""
    try:
        if source.is_dir():
            return source
        shared = 0
        for left, right in zip(source.parts, reference.parts):
            if os.path.normcase(left) != os.path.normcase(right):
                break
            shared += 1
        if not shared:
            return source
        recovered = Path(*reference.parts[:shared])
        if not recovered.is_dir():
            return source
        for part in source.parts[shared:]:
            matches = [p for p in recovered.iterdir() if os.path.normcase(p.name) == os.path.normcase(part)]
            if len(matches) != 1:
                return source
            recovered = matches[0]
        return recovered if recovered.is_dir() else source
    except OSError:
        return source


@dataclass(frozen=True)
class AppPaths:
    """Paths are anchored to the directory containing the executable/source tree."""

    root: Path
    source: Path = DEFAULT_SOURCE
    sources: tuple[Path, ...] = ()
    data_dir: Path | None = None
    output_dir: Path | None = None

    def __post_init__(self):
        sources = normalize_sources(self.sources or (self.source,))
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "source", sources[0])

    @property
    def library(self) -> Path:
        return self.data_dir or (self.root / "Library")

    @property
    def database(self) -> Path:
        return self.library / "library.sqlite3"

    @property
    def overrides(self) -> Path:
        return self.library / "Overrides"

    @property
    def compiled(self) -> Path:
        return self.output_dir or (self.library / "Compiled")

    def ensure(self) -> None:
        self.library.mkdir(parents=True, exist_ok=True)
        self.overrides.mkdir(parents=True, exist_ok=True)
        self.compiled.mkdir(parents=True, exist_ok=True)


def project_paths(root: Path | None = None, source: Path | None = None) -> AppPaths:
    settings_path = user_settings_path()
    settings = {}
    if root is None:
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if root is not None:
        base = root
    elif getattr(sys, "frozen", False):
        # PyInstaller puts the executable at <project>/dist/ChartOrganizer.
        # Keep mutable library data outside dist, which the rebuild replaces.
        executable_dir = Path(sys.executable).resolve().parent
        base = executable_dir.parent.parent if executable_dir.parent.name.casefold() == "dist" else executable_dir
    else:
        base = Path(__file__).resolve().parent.parent
    base = base.resolve()
    sources = settings.get("sources") or [str(source or DEFAULT_SOURCE)]
    default_data = (Path(root) / "Library" if root is not None else
                    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ChartOrganizer" / "Library")
    legacy_data = base / "Library"
    data_dir = Path(settings["data_dir"]) if settings.get("data_dir") else (legacy_data if legacy_data.exists() else default_data)
    output_dir = Path(settings["output_dir"]) if settings.get("output_dir") else data_dir / "Compiled"
    return AppPaths(base, Path(sources[0]), tuple(Path(p) for p in sources), data_dir, output_dir)


def user_settings_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "ChartOrganizer" / "settings.json"


def save_user_settings(paths: AppPaths) -> None:
    destination = user_settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"sources": [str(p) for p in paths.sources],
                                    "data_dir": str(paths.library), "output_dir": str(paths.compiled)}, indent=2),
                         encoding="utf-8")
    temporary.replace(destination)


def migrate_library(source: Path, destination: Path) -> None:
    """Copy a library before switching settings; retain the source as a recovery copy."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        return
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    if (source / "library.sqlite3").exists() and not (destination / "library.sqlite3").exists():
        raise OSError("Library copy did not include its database")
    copied_database = destination / "library.sqlite3"
    if copied_database.exists():
        with sqlite3.connect(copied_database) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise sqlite3.DatabaseError(f"Copied library failed its integrity check: {result[0] if result else 'no result'}")

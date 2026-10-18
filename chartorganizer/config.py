from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import os


DEFAULT_SOURCE = Path(
    r"G:\.shortcut-targets-by-id\1MODds_qN97PC6U0g5OnRKRAP5YeI8rzY\COMMUNITY STREET BAND\Active Repertoire"
)


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

    def __post_init__(self):
        sources = normalize_sources(self.sources or (self.source,))
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "source", sources[0])

    @property
    def library(self) -> Path:
        return self.root / "Library"

    @property
    def database(self) -> Path:
        return self.library / "library.sqlite3"

    @property
    def overrides(self) -> Path:
        return self.library / "Overrides"

    @property
    def compiled(self) -> Path:
        return self.library / "Compiled"

    def ensure(self) -> None:
        self.library.mkdir(parents=True, exist_ok=True)
        self.overrides.mkdir(parents=True, exist_ok=True)
        self.compiled.mkdir(parents=True, exist_ok=True)


def project_paths(root: Path | None = None, source: Path | None = None) -> AppPaths:
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
    return AppPaths(base, source or DEFAULT_SOURCE)

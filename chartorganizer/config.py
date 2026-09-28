from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


DEFAULT_SOURCE = Path(
    r"G:\.shortcut-targets-by-id\1MODds_qN97PC6U0g5OnRKRAP5YeI8rzY\COMMUNITY STREET BAND\Active Repertoire"
)


@dataclass(frozen=True)
class AppPaths:
    """Paths are anchored to the directory containing the executable/source tree."""

    root: Path
    source: Path = DEFAULT_SOURCE

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

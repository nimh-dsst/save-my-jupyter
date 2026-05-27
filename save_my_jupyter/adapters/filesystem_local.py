"""Local read-only `FileSystem` adapter over pathlib. Capture reads notebook and
watched-file bytes through this seam and resolves watched-path globs with it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


class LocalFileSystem:
    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def iter_files(self, root: Path, pattern: str) -> Iterator[Path]:
        for candidate in sorted(root.glob(pattern)):
            if candidate.is_file():
                yield candidate

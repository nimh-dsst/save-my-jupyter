from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol


class FileSystem(Protocol):
    """Read-only filesystem seam used by capture to read notebook and
    watched-file bytes and to resolve watched-path globs.

    This is a read-only adapter, not a pure dependency: the same call can return
    different results as the filesystem changes (contract C-CONFIG-02 — the
    Activity receipt, not the preview, is authoritative for what was uploaded).
    """

    def exists(self, path: Path) -> bool: ...

    def is_file(self, path: Path) -> bool: ...

    def read_bytes(self, path: Path) -> bytes: ...

    def iter_files(self, root: Path, pattern: str) -> Iterator[Path]: ...

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.provenance import ConfigLayer

if TYPE_CHECKING:
    from save_my_jupyter.ports import Clock, FileSystem, KeyringStore


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 5, 26, tzinfo=UTC)


class _MemoryKeyring:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


class _MemoryFileSystem:
    def __init__(self, files: dict[Path, bytes]) -> None:
        self._files = files

    def exists(self, path: Path) -> bool:
        return path in self._files

    def is_file(self, path: Path) -> bool:
        return path in self._files

    def read_bytes(self, path: Path) -> bytes:
        return self._files[path]

    def iter_files(self, root: Path, pattern: str) -> Iterator[Path]:
        del pattern
        for candidate in self._files:
            if candidate == root or root in candidate.parents:
                yield candidate


def test_fakes_satisfy_port_protocols() -> None:
    # The typed bindings are the real assertion: ty rejects a fake that does not
    # structurally satisfy the Protocol. The runtime checks confirm behavior.
    clock: Clock = _FixedClock()
    keyring: KeyringStore = _MemoryKeyring()
    filesystem: FileSystem = _MemoryFileSystem({Path("/repo/a.py"): b"x"})

    assert clock.now().tzinfo is UTC

    keyring.set_password("svc", "user", "secret")
    assert keyring.get_password("svc", "user") == "secret"
    keyring.delete_password("svc", "user")
    assert keyring.get_password("svc", "user") is None

    assert filesystem.is_file(Path("/repo/a.py"))
    assert filesystem.read_bytes(Path("/repo/a.py")) == b"x"
    assert list(filesystem.iter_files(Path("/repo"), "*")) == [Path("/repo/a.py")]


def test_domain_enums_have_expected_wire_values() -> None:
    assert JobState.ABANDONED == "abandoned"
    assert RunOutcome.ERROR == "error"
    assert RunOutcome.NOT_APPLICABLE == "n/a"
    assert ConfigLayer.INFERRED == "inferred"
    assert [layer.value for layer in ConfigLayer] == [
        "request",
        "notebook",
        "user",
        "repo",
        "inferred",
        "fallback",
    ]

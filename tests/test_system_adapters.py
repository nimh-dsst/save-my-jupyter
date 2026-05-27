from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.clock_system import SystemClock
from save_my_jupyter.adapters.filesystem_local import LocalFileSystem
from save_my_jupyter.adapters.keyring_system import SystemKeyring

if TYPE_CHECKING:
    import pytest
    from save_my_jupyter.ports import Clock, FileSystem, KeyringStore


def test_system_clock_returns_utc_now() -> None:
    clock: Clock = SystemClock()
    assert clock.now().tzinfo is UTC


def test_local_filesystem_reads_and_globs(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.csv").write_bytes(b"y")

    filesystem: FileSystem = LocalFileSystem()
    assert filesystem.exists(tmp_path / "a.csv")
    assert filesystem.is_file(tmp_path / "a.csv")
    assert not filesystem.is_file(tmp_path / "sub")
    assert filesystem.read_bytes(tmp_path / "a.csv") == b"x"

    found = list(filesystem.iter_files(tmp_path, "**/*.csv"))
    assert found == [tmp_path / "a.csv", tmp_path / "sub" / "b.csv"]


def test_system_keyring_delegates_to_keyring_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[tuple[str, str], str] = {}
    base = "save_my_jupyter.adapters.keyring_system.keyring"
    monkeypatch.setattr(
        f"{base}.set_password",
        lambda service, username, password: store.update(
            {(service, username): password}
        ),
    )
    monkeypatch.setattr(
        f"{base}.get_password",
        lambda service, username: store.get((service, username)),
    )
    monkeypatch.setattr(
        f"{base}.delete_password",
        lambda service, username: store.pop((service, username), None),
    )

    keyring_store: KeyringStore = SystemKeyring()
    keyring_store.set_password("svc", "user", "secret")
    assert keyring_store.get_password("svc", "user") == "secret"
    keyring_store.delete_password("svc", "user")
    assert keyring_store.get_password("svc", "user") is None

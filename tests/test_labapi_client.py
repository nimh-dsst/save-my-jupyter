from __future__ import annotations

from typing import TYPE_CHECKING, Any

from save_my_jupyter.adapters.labarchives import labapi_client as labapi_client_module
from save_my_jupyter.adapters.labarchives.labapi_client import LabApiClient

if TYPE_CHECKING:
    import pytest


class _InsertBehavior:
    Raise = "raise"


class _SnapshotDirectory:
    def __init__(self, *, directory_id: str, url: str | None = None) -> None:
        self.id = directory_id
        self.url = url


class _SnapshotDirectoryWithMethod:
    def __init__(self, *, directory_id: str, url: str) -> None:
        self.id = directory_id
        self._url = url

    def get_url(self) -> str:
        return self._url


class _RootDirectory:
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot
        self.segments: list[str] = []

    def dir(self, segment: str) -> _RootDirectory:
        self.segments.append(segment)
        return self

    def create(self, kind: object, name: str, *, if_exists: object) -> Any:
        del kind, name, if_exists
        return self.snapshot


class _Notebooks:
    def __init__(self, root: _RootDirectory) -> None:
        self.root = root

    def __getitem__(self, notebook_name: str) -> _RootDirectory:
        del notebook_name
        return self.root


class _Session:
    def __init__(self, root: _RootDirectory) -> None:
        self.user = type("User", (), {"notebooks": _Notebooks(root)})()


def _install_labapi_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        labapi_client_module.labapi, "InsertBehavior", _InsertBehavior, raising=False
    )
    monkeypatch.setattr(
        labapi_client_module.labapi, "NotebookDirectory", object(), raising=False
    )


def test_directory_url_uses_created_directory_url_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_labapi_constants(monkeypatch)
    root = _RootDirectory(
        _SnapshotDirectory(
            directory_id="dir-1", url="https://labarchives.test/dirs/dir-1"
        )
    )
    client = LabApiClient(_Session(root))

    directory_id = client.create_directory(
        notebook_name="Jupyter Snapshots",
        root_path="Notebook Log/user@example.com",
        directory_name="snapshot-1",
    )

    assert directory_id == "dir-1"
    assert root.segments == ["Notebook Log", "user@example.com"]
    assert (
        client.directory_url(directory_id="dir-1")
        == "https://labarchives.test/dirs/dir-1"
    )


def test_directory_url_uses_created_directory_url_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_labapi_constants(monkeypatch)
    root = _RootDirectory(
        _SnapshotDirectoryWithMethod(
            directory_id="dir-2", url="https://labarchives.test/dirs/dir-2"
        )
    )
    client = LabApiClient(_Session(root))

    directory_id = client.create_directory(
        notebook_name="Jupyter Snapshots",
        root_path="Notebook Log",
        directory_name="snapshot-2",
    )

    assert directory_id == "dir-2"
    assert (
        client.directory_url(directory_id="dir-2")
        == "https://labarchives.test/dirs/dir-2"
    )


def test_directory_url_ignores_unknown_or_non_clickable_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_labapi_constants(monkeypatch)
    root = _RootDirectory(_SnapshotDirectory(directory_id="dir-3", url="/dirs/dir-3"))
    client = LabApiClient(_Session(root))

    client.create_directory(
        notebook_name="Jupyter Snapshots",
        root_path="Notebook Log",
        directory_name="snapshot-3",
    )

    assert client.directory_url(directory_id="dir-3") is None
    assert client.directory_url(directory_id="missing") is None

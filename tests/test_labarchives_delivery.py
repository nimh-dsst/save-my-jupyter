from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from save_my_jupyter.adapters.labarchives.delivery import LabArchivesDelivery
from save_my_jupyter.application.snapshot.build import build_snapshot_bundle
from save_my_jupyter.domain.artifacts import NotebookPayload, WatchedFileArtifact
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import SnapshotBundle, SnapshotMetadata
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    MimeType,
    SnapshotId,
)

if TYPE_CHECKING:
    from save_my_jupyter.ports import Delivery


class _FakeClient:
    def __init__(self, *, fail_on_attach: bool = False) -> None:
        self.pages: list[str] = []
        self.deleted: list[str] = []
        self.attachments: list[str] = []
        self._fail_on_attach = fail_on_attach
        self._counter = 0

    def create_directory(
        self, *, notebook_name: str, root_path: str, directory_name: str
    ) -> str:
        return f"dir::{directory_name}"

    def create_page(self, *, directory_id: str, page_name: str) -> str:
        self._counter += 1
        page_id = f"page-{self._counter}"
        self.pages.append(page_name)
        return page_id

    def write_page_html(self, *, page_id: str, html: str) -> None:
        del page_id, html

    def attach_file(
        self, *, page_id: str, filename: str, mime_type: str, content: bytes
    ) -> None:
        del page_id, mime_type, content
        if self._fail_on_attach:
            raise RuntimeError("labarchives attach failed")
        self.attachments.append(filename)

    def delete_directory(self, *, directory_id: str) -> None:
        self.deleted.append(directory_id)

    def directory_url(self, *, directory_id: str) -> str | None:
        return f"https://labarchives.test/{directory_id}"


def _bundle() -> SnapshotBundle:
    metadata = SnapshotMetadata(
        notebook_name="nb.ipynb",
        notebook_path="proj/nb.ipynb",
        source=SnapshotSource.MANUAL,
        run_outcome=RunOutcome.NOT_APPLICABLE,
        snapshot_id=SnapshotId("snap-1"),
        run_fingerprint=None,
        trigger_cells=(),
        commit_hash=None,
        commit_status="none",
        commit_url=None,
        diff_included=False,
        extension_version="0.1.0",
        run_label=None,
        tags=(),
        notes=None,
        execution_summary="ok",
    )
    return build_snapshot_bundle(
        directory_name="2026-05-26T12-00-00.000_snap-1",
        target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
            root_path=LabArchivesRootPath("Notebook Log/a@b.org"),
        ),
        metadata=metadata,
        notebook=NotebookPayload(filename="nb.ipynb", content=b"{}"),
        files=(
            WatchedFileArtifact(
                filename="result.csv", mime_type=MimeType("text/csv"), content=b"a,b"
            ),
        ),
    )


def test_successful_delivery_creates_pages_and_returns_receipt() -> None:
    client = _FakeClient()
    delivery: Delivery = LabArchivesDelivery(client)
    receipt = delivery.deliver(_bundle())

    # metadata page + notebook + watched file
    assert client.pages == ["00 Metadata", "nb.ipynb", "result.csv"]
    assert receipt.meta_page_name == "00 Metadata"
    assert receipt.page_count == 3
    assert receipt.directory_name == "2026-05-26T12-00-00.000_snap-1"
    assert receipt.url is not None
    assert client.deleted == []


def test_failed_delivery_cleans_up_and_raises() -> None:
    client = _FakeClient(fail_on_attach=True)
    delivery = LabArchivesDelivery(client)
    with pytest.raises(SnapshotError) as exc:
        delivery.deliver(_bundle())
    assert exc.value.code == "labarchives_write_failed"
    # best-effort cleanup moved the directory to API Deleted Items
    assert client.deleted == ["dir::2026-05-26T12-00-00.000_snap-1"]

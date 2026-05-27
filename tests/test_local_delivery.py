from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.local_delivery import LocalDelivery
from save_my_jupyter.application.snapshot.build import build_snapshot_bundle
from save_my_jupyter.domain.artifacts import FigureArtifact, NotebookPayload
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import SnapshotBundle, SnapshotMetadata
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    MimeType,
    SnapshotId,
)

if TYPE_CHECKING:
    from save_my_jupyter.ports import Delivery


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
            root_path=LabArchivesRootPath("Notebook Log"),
        ),
        metadata=metadata,
        notebook=NotebookPayload(filename="nb.ipynb", content=b'{"cells": []}'),
        figures=(
            FigureArtifact(
                name="figure-001.png", mime_type=MimeType("image/png"), content=b"PNG"
            ),
        ),
    )


def test_writes_snapshot_directory_with_pages_and_metadata(tmp_path: Path) -> None:
    delivery: Delivery = LocalDelivery(tmp_path)
    receipt = delivery.deliver(_bundle())

    directory = tmp_path / "2026-05-26T12-00-00.000_snap-1"
    assert (directory / "00 Metadata.html").is_file()
    assert "Snapshot metadata" in (directory / "00 Metadata.html").read_text("utf-8")
    assert (directory / "nb.ipynb").read_bytes() == b'{"cells": []}'
    assert (directory / "figure-001.png").read_bytes() == b"PNG"

    assert receipt.meta_page_name == "00 Metadata"
    assert receipt.page_count == 3  # metadata + notebook + figure
    assert receipt.url is not None
    assert receipt.url.startswith("file:")


def test_each_snapshot_gets_its_own_directory(tmp_path: Path) -> None:
    delivery = LocalDelivery(tmp_path)
    delivery.deliver(_bundle())
    directories = sorted(child.name for child in tmp_path.iterdir() if child.is_dir())
    assert directories == ["2026-05-26T12-00-00.000_snap-1"]

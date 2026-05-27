from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.fake_delivery import FakeDelivery
from save_my_jupyter.application.snapshot.build import (
    build_snapshot_bundle,
    format_directory_name,
)
from save_my_jupyter.application.snapshot.diff import DIFF_FILTER_QUALIFIER
from save_my_jupyter.domain.artifacts import (
    FigureArtifact,
    NotebookPayload,
    WatchedFileArtifact,
)
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import SnapshotMetadata
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

_TARGET = LabArchivesTarget(
    notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
    root_path=LabArchivesRootPath("Notebook Log/a@b.org"),
)


def _metadata() -> SnapshotMetadata:
    return SnapshotMetadata(
        notebook_name="analysis.ipynb",
        notebook_path="analysis/analysis.ipynb",
        source=SnapshotSource.MANUAL,
        run_outcome=RunOutcome.NOT_APPLICABLE,
        snapshot_id=SnapshotId("snapshot-1"),
        run_fingerprint=None,
        trigger_cells=(),
        commit_hash=None,
        commit_status="none",
        commit_url=None,
        diff_included=False,
        extension_version="0.1.0",
        run_label=None,
        tags=("baseline",),
        notes=None,
        execution_summary="42",
    )


# --- directory naming (C-DEST-01) ---


def test_directory_name_uses_iso_millisecond_timestamp_and_snapshot_id() -> None:
    name = format_directory_name(
        timestamp=datetime(2026, 5, 26, 12, 0, 0, 123000, tzinfo=UTC),
        snapshot_id=SnapshotId("snapshot-1"),
    )
    assert name == "2026-05-26T12-00-00.123_snapshot-1"


# --- bundle assembly (C-DEST-03, C-CONTENT order) ---


def test_bundle_orders_notebook_then_files_then_diff_and_embeds_figures() -> None:
    bundle = build_snapshot_bundle(
        directory_name="dir-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=NotebookPayload(filename="analysis.ipynb", content=b"{}"),
        figures=(
            FigureArtifact(
                name="figure-001.png", mime_type=MimeType("image/png"), content=b"img"
            ),
        ),
        files=(
            WatchedFileArtifact(
                filename="result.csv",
                mime_type=MimeType("text/csv"),
                content=b"a,b",
            ),
        ),
        diff_text="diff --git a/x b/x",
    )
    assert [artifact.page_name for artifact in bundle.artifacts] == [
        "analysis.ipynb",
        "result.csv",
        "working-tree.patch",
    ]
    assert bundle.artifacts[0].mime_type == "application/x-ipynb+json"
    assert bundle.artifacts[-1].mime_type == "text/x-diff"
    assert bundle.artifacts[-1].content == b"diff --git a/x b/x"
    assert bundle.artifacts[-1].description == DIFF_FILTER_QUALIFIER


def test_bundle_omits_notebook_when_absent() -> None:
    bundle = build_snapshot_bundle(
        directory_name="dir-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=None,
    )
    assert bundle.artifacts == ()


def test_bundle_keeps_figures_when_notebook_is_absent() -> None:
    bundle = build_snapshot_bundle(
        directory_name="dir-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=None,
        figures=(
            FigureArtifact(
                name="figure-001.png", mime_type=MimeType("image/png"), content=b"img"
            ),
        ),
    )

    assert [artifact.page_name for artifact in bundle.artifacts] == ["figure-001.png"]


def test_bundle_omits_diff_when_blank() -> None:
    bundle = build_snapshot_bundle(
        directory_name="dir-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=NotebookPayload(filename="n.ipynb", content=b"{}"),
        diff_text="",
    )
    assert [a.page_name for a in bundle.artifacts] == ["n.ipynb"]


def test_page_name_truncated_to_120_chars() -> None:
    long_name = "x" * 200 + ".csv"
    bundle = build_snapshot_bundle(
        directory_name="dir-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=None,
        files=(
            WatchedFileArtifact(
                filename=long_name, mime_type=MimeType("text/csv"), content=b""
            ),
        ),
    )
    assert len(bundle.artifacts[0].page_name) == 120


# --- FakeDelivery (test/dev double for the Delivery port) ---


def test_fake_delivery_receipt_counts_metadata_plus_artifacts() -> None:
    delivery = FakeDelivery()
    bundle = build_snapshot_bundle(
        directory_name="2026-05-26T12-00-00.123_snapshot-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=NotebookPayload(filename="n.ipynb", content=b"{}"),
        figures=(
            FigureArtifact(
                name="figure-001.png", mime_type=MimeType("image/png"), content=b"i"
            ),
        ),
    )
    receipt = delivery.deliver(bundle)

    # one 00 Metadata page + notebook; figures are embedded in the notebook page.
    assert receipt.page_count == 2
    assert receipt.meta_page_name == "00 Metadata"
    assert receipt.directory_name == "2026-05-26T12-00-00.123_snapshot-1"
    assert receipt.url is not None
    assert "2026-05-26T12-00-00.123_snapshot-1" in receipt.url


def test_fake_delivery_records_each_delivered_bundle() -> None:
    delivery = FakeDelivery()
    bundle = build_snapshot_bundle(
        directory_name="dir-1",
        target=_TARGET,
        metadata=_metadata(),
        notebook=None,
    )
    delivery.deliver(bundle)
    assert delivery.delivered == [bundle]


def test_fake_delivery_satisfies_the_delivery_port() -> None:
    # `ty` verifies structural conformance to the Protocol via this annotation.
    delivery: Delivery = FakeDelivery()
    assert delivery is not None

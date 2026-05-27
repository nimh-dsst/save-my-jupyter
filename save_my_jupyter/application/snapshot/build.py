"""Pure bundle building (target CAPTURE -> DELIVER seam). Assembles already-read
artifacts into the ordered set of pages one snapshot delivers, and formats the
unique snapshot directory name. No IO: bytes are supplied by the reader."""

from __future__ import annotations

from datetime import datetime

from save_my_jupyter.application.snapshot.notebook_content import NOTEBOOK_MIME_TYPE
from save_my_jupyter.domain.artifacts import (
    FigureArtifact,
    NotebookPayload,
    WatchedFileArtifact,
)
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import (
    BundleArtifact,
    SnapshotBundle,
    SnapshotMetadata,
)
from save_my_jupyter.domain.types import MimeType, SnapshotId

_PAGE_NAME_MAX = 120
_DIFF_MIME_TYPE = MimeType("text/x-diff")
_DIFF_PAGE_NAME = "working-tree.patch"


def format_directory_name(*, timestamp: datetime, snapshot_id: SnapshotId) -> str:
    """``<iso-millisecond-timestamp>_<snapshot-id>`` with path-safe separators
    (contract C-DEST-01). The snapshot id keeps back-to-back names distinct."""
    millis = timestamp.microsecond // 1000
    stamp = f"{timestamp.strftime('%Y-%m-%dT%H-%M-%S')}.{millis:03d}"
    return f"{stamp}_{snapshot_id}"


def build_snapshot_bundle(
    *,
    directory_name: str,
    target: LabArchivesTarget,
    metadata: SnapshotMetadata,
    notebook: NotebookPayload | None,
    figures: tuple[FigureArtifact, ...] = (),
    files: tuple[WatchedFileArtifact, ...] = (),
    diff_text: str | None = None,
) -> SnapshotBundle:
    artifacts: list[BundleArtifact] = []

    if notebook is not None:
        artifacts.append(
            BundleArtifact(
                page_name=_page_name(notebook.filename),
                mime_type=NOTEBOOK_MIME_TYPE,
                content=notebook.content,
            )
        )
    for figure in figures:
        artifacts.append(
            BundleArtifact(
                page_name=_page_name(figure.name),
                mime_type=figure.mime_type,
                content=figure.content,
            )
        )
    for watched_file in files:
        artifacts.append(
            BundleArtifact(
                page_name=_page_name(watched_file.filename),
                mime_type=watched_file.mime_type,
                content=watched_file.content,
            )
        )
    if diff_text:
        artifacts.append(
            BundleArtifact(
                page_name=_DIFF_PAGE_NAME,
                mime_type=_DIFF_MIME_TYPE,
                content=diff_text.encode("utf-8"),
            )
        )

    return SnapshotBundle(
        directory_name=directory_name,
        target=target,
        metadata=metadata,
        artifacts=tuple(artifacts),
    )


def _page_name(filename: str) -> str:
    basename = filename.rsplit("/", 1)[-1]
    return basename[:_PAGE_NAME_MAX]

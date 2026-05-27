from __future__ import annotations

from dataclasses import dataclass

from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    CellId,
    CommitHash,
    MimeType,
    RemoteUrl,
    RunFingerprint,
    SnapshotId,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotMetadata:
    """The fields rendered onto the ``00 Metadata`` page (contract C-DEST-02).
    A pure value object; the delivery adapter renders it to the page table."""

    notebook_name: str
    notebook_path: str
    source: SnapshotSource
    run_outcome: RunOutcome
    snapshot_id: SnapshotId
    run_fingerprint: RunFingerprint | None
    trigger_cells: tuple[CellId, ...]
    commit_hash: CommitHash | None
    commit_status: str
    commit_url: RemoteUrl | None
    diff_included: bool
    extension_version: str
    run_label: str | None
    tags: tuple[str, ...]
    notes: str | None
    execution_summary: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BundleArtifact:
    """One page's worth of content in a snapshot directory (contract C-DEST-03)."""

    page_name: str
    mime_type: MimeType
    content: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotBundle:
    """Everything one snapshot delivers: a directory, its metadata page, and the
    artifact pages, addressed at a LabArchives target."""

    directory_name: str
    target: LabArchivesTarget
    metadata: SnapshotMetadata
    artifacts: tuple[BundleArtifact, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryReceipt:
    """What a successful delivery returns to the user (contract C-DEST-05)."""

    directory_name: str
    meta_page_id: str
    meta_page_name: str
    page_count: int
    url: RemoteUrl | None

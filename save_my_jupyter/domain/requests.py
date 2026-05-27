from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    CellId,
    DocumentId,
    KernelId,
    NotebookPath,
    RelativeWatchPath,
    StringMap,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookContext:
    """Identity and run context for the notebook a snapshot targets."""

    notebook_path: NotebookPath
    notebook_name: str
    document_id: DocumentId | None = None
    kernel_id: KernelId | None = None
    triggering_cell_id: CellId | None = None
    triggered_cell_ids: tuple[CellId, ...] = ()
    cell_execution_count: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestedMetadata:
    """User-entered metadata travelling with a snapshot request (C-CONTENT-08)."""

    tags: tuple[str, ...] = ()
    run_label: str | None = None
    notes: str | None = None
    extra_fields: StringMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotRequest:
    """A parsed snapshot request from the HTTP boundary. Watched paths travel in
    the body (C-API-04) and the optional in-memory notebook content lets capture
    honor unsaved edits (preferred over disk; contract C-CONFIG-02)."""

    source: SnapshotSource
    notebook_context: NotebookContext
    metadata: RequestedMetadata
    commit_mode: CommitMode | None = None
    watched_paths: tuple[RelativeWatchPath, ...] | None = None
    run_outcome: RunOutcome | None = None
    client_timestamp: datetime | None = None
    notebook_content: Mapping[str, object] | None = field(default=None, compare=False)

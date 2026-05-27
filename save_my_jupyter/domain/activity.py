from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.types import CommitHash, RemoteUrl, SnapshotId


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityRecord:
    """One durable row of snapshot history (contract C-QUEUE-06). Holds only
    references and outcomes — never auth tokens, notebook or watched-file
    contents, tags, run labels, notes, or diffs. The dedupe fingerprint is
    deliberately absent: dedupe state is in-memory and resets on restart."""

    job_id: str
    submitted_at: datetime
    completed_at: datetime | None
    source: SnapshotSource
    notebook_path: str
    state: JobState
    run_outcome: RunOutcome
    snapshot_id: SnapshotId | None
    commit_hash: CommitHash | None
    commit_url: RemoteUrl | None
    directory_name: str | None
    directory_url: RemoteUrl | None
    meta_page_id: str | None
    meta_page_name: str | None
    page_count: int | None
    error_code: str | None
    error_message: str | None
    display_message: str

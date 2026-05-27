"""Canonical, backend-authoritative display messages (target CONFIRM). The
Activity store persists this string (contract C-QUEUE-06) and both the panel
receipt and JupyterLab notifications render it, so the message lives here once
rather than being reconstructed per surface. Pure string assembly."""

from __future__ import annotations

from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState

_RUNNING_MESSAGE = (
    "Saving notebook, creating snapshot artifacts, and uploading to LabArchives."
)
_QUEUED_MESSAGE = "Snapshot queued."
_ABANDONED_MESSAGE = "Snapshot abandoned when the Jupyter server restarted."
_MANUAL_FAILURE = "Unable to save the snapshot."
_TRIGGER_FAILURE = "Save My Jupyter trigger snapshot failed."
_SHORT_HASH_LENGTH = 12


def build_display_message(
    *,
    state: JobState,
    source: SnapshotSource,
    job_id: str,
    snapshot_id: str | None = None,
    commit_hash: str | None = None,
    commit_status: str = "none",
    commit_url: str | None = None,
    directory_url: str | None = None,
    meta_page_name: str | None = None,
    meta_page_id: str | None = None,
    error_message: str | None = None,
) -> str:
    match state:
        case JobState.PERSISTED:
            return _persisted_message(
                job_id=job_id,
                snapshot_id=snapshot_id,
                commit_hash=commit_hash,
                commit_status=commit_status,
                commit_url=commit_url,
                directory_url=directory_url,
                meta_page_name=meta_page_name,
                meta_page_id=meta_page_id,
            )
        case JobState.RUNNING:
            return _RUNNING_MESSAGE
        case JobState.QUEUED:
            return _QUEUED_MESSAGE
        case JobState.ABANDONED:
            return _ABANDONED_MESSAGE
        case JobState.FAILED:
            if error_message:
                return error_message
            if source is SnapshotSource.TRIGGER_CELL:
                return _TRIGGER_FAILURE
            return _MANUAL_FAILURE


def _persisted_message(
    *,
    job_id: str,
    snapshot_id: str | None,
    commit_hash: str | None,
    commit_status: str,
    commit_url: str | None,
    directory_url: str | None,
    meta_page_name: str | None,
    meta_page_id: str | None,
) -> str:
    clauses = [f"Job {job_id}."]
    if snapshot_id:
        clauses.append(f"Snapshot {snapshot_id}.")
    if commit_hash:
        short = _short_hash(commit_hash)
        if commit_status == "created":
            clauses.append(f"Commit {short} created.")
        elif commit_status == "reused":
            clauses.append(f"Existing HEAD {short} reused.")
    if commit_url:
        clauses.append(f"Commit URL: {commit_url}.")
    if directory_url:
        clauses.append(f"LabArchives {directory_url}.")
    elif meta_page_name:
        clauses.append(f"LabArchives page {meta_page_name}.")
    elif meta_page_id:
        clauses.append(f"LabArchives page {meta_page_id}.")
    return "Snapshot saved. " + " ".join(clauses)


def _short_hash(commit_hash: str) -> str:
    if len(commit_hash) > _SHORT_HASH_LENGTH:
        return commit_hash[:_SHORT_HASH_LENGTH]
    return commit_hash

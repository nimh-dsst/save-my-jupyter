from __future__ import annotations

import pytest
from save_my_jupyter.application.activity.transitions import (
    abandon_if_pending,
    can_transition,
    is_terminal,
)
from save_my_jupyter.application.confirm.messages import build_display_message
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState

# --- state machine (C-QUEUE-05) ---


def test_valid_transitions() -> None:
    assert can_transition(JobState.QUEUED, JobState.RUNNING)
    assert can_transition(JobState.RUNNING, JobState.PERSISTED)
    assert can_transition(JobState.RUNNING, JobState.FAILED)
    assert can_transition(JobState.QUEUED, JobState.ABANDONED)
    assert can_transition(JobState.RUNNING, JobState.ABANDONED)


def test_invalid_transitions() -> None:
    assert not can_transition(JobState.PERSISTED, JobState.RUNNING)
    assert not can_transition(JobState.FAILED, JobState.PERSISTED)
    assert not can_transition(JobState.QUEUED, JobState.PERSISTED)
    assert not can_transition(JobState.ABANDONED, JobState.RUNNING)


def test_terminal_states() -> None:
    assert is_terminal(JobState.PERSISTED)
    assert is_terminal(JobState.FAILED)
    assert is_terminal(JobState.ABANDONED)
    assert not is_terminal(JobState.QUEUED)
    assert not is_terminal(JobState.RUNNING)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (JobState.QUEUED, JobState.ABANDONED),
        (JobState.RUNNING, JobState.ABANDONED),
        (JobState.PERSISTED, JobState.PERSISTED),
        (JobState.FAILED, JobState.FAILED),
        (JobState.ABANDONED, JobState.ABANDONED),
    ],
)
def test_abandon_if_pending_only_touches_inflight(
    state: JobState, expected: JobState
) -> None:
    assert abandon_if_pending(state) is expected


# --- display message (C-SNAP-04/05/06, C-DEST-05) ---


def test_persisted_message_orders_reference_clauses() -> None:
    message = build_display_message(
        state=JobState.PERSISTED,
        source=SnapshotSource.MANUAL,
        job_id="job-42",
        snapshot_id="snapshot-1",
        commit_hash="abcdef1234567890",
        commit_status="created",
        commit_url="https://git.example.test/c/abcdef1234567890",
        directory_url="https://labarchives.test/snapshots/dir-1",
        meta_page_name="00 Metadata",
        error_message=None,
    )
    assert message.startswith("Snapshot saved.")
    assert "Job job-42." in message
    assert "Snapshot snapshot-1." in message
    assert "Commit abcdef123456 created." in message
    assert "Commit URL: https://git.example.test/c/abcdef1234567890." in message
    assert "LabArchives https://labarchives.test/snapshots/dir-1." in message


def test_persisted_message_reuses_existing_head_when_not_created() -> None:
    message = build_display_message(
        state=JobState.PERSISTED,
        source=SnapshotSource.MANUAL,
        job_id="job-1",
        commit_hash="abcdef1234567890",
        commit_status="reused",
    )
    assert "Existing HEAD abcdef123456 reused." in message
    assert "created." not in message


def test_persisted_message_omits_missing_clauses() -> None:
    message = build_display_message(
        state=JobState.PERSISTED,
        source=SnapshotSource.MANUAL,
        job_id="job-1",
    )
    assert message == "Snapshot saved. Job job-1."


def test_persisted_message_falls_back_to_page_name_without_url() -> None:
    message = build_display_message(
        state=JobState.PERSISTED,
        source=SnapshotSource.MANUAL,
        job_id="job-1",
        meta_page_name="00 Metadata",
    )
    assert "LabArchives page 00 Metadata." in message


def test_running_message() -> None:
    message = build_display_message(
        state=JobState.RUNNING, source=SnapshotSource.MANUAL, job_id="job-1"
    )
    assert message == (
        "Saving notebook, creating snapshot artifacts, and uploading to LabArchives."
    )


def test_failed_message_uses_specific_error_when_present() -> None:
    message = build_display_message(
        state=JobState.FAILED,
        source=SnapshotSource.MANUAL,
        job_id="job-1",
        error_message="LabArchives session expired.",
    )
    assert message == "LabArchives session expired."


def test_failed_manual_fallback_message() -> None:
    message = build_display_message(
        state=JobState.FAILED, source=SnapshotSource.MANUAL, job_id="job-1"
    )
    assert message == "Unable to save the snapshot."


def test_failed_trigger_fallback_message() -> None:
    message = build_display_message(
        state=JobState.FAILED, source=SnapshotSource.TRIGGER_CELL, job_id="job-1"
    )
    assert message == "Save My Jupyter trigger snapshot failed."

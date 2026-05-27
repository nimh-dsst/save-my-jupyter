from __future__ import annotations

from datetime import UTC, datetime

from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.capture import CapturePlan, PlannedArtifact
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.enums import ArtifactKind, SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.provenance import ConfigLayer
from save_my_jupyter.domain.queue import Accepted, Coalesced, Rejected
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    RemoteUrl,
    SnapshotId,
)
from save_my_jupyter.transport.responses import (
    serialize_activity,
    serialize_error,
    serialize_preview,
    serialize_submission,
)

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


# --- error envelope (C-API-02) ---


def test_error_envelope_shape() -> None:
    error = SnapshotError(
        "bad path", code="path_escapes_root", context={"path": "a/../b"}
    )
    assert serialize_error(error) == {
        "error": {
            "code": "path_escapes_root",
            "message": "bad path",
            "context": {"path": "a/../b"},
        }
    }


# --- async submission result (C-API-04, C-QUEUE-02) ---


def test_accepted_submission() -> None:
    assert serialize_submission(Accepted(job_id="job-1")) == {
        "jobId": "job-1",
        "status": "accepted",
    }


def test_coalesced_submission_is_accepted_with_correlation() -> None:
    result = serialize_submission(Coalesced(job_id="job-2", coalesced_into="job-1"))
    assert result["status"] == "accepted"
    assert result["jobId"] == "job-2"
    assert result["coalescedInto"] == "job-1"


def test_rejected_submission() -> None:
    result = serialize_submission(
        Rejected(reason_code="duplicate_run", message="A snapshot already exists.")
    )
    assert result == {
        "status": "rejected",
        "reasonCode": "duplicate_run",
        "message": "A snapshot already exists.",
    }


# --- activity record (C-API-04 job state) ---


def test_activity_record_serializes_to_camel_case() -> None:
    record = ActivityRecord(
        job_id="job-1",
        submitted_at=_NOW,
        completed_at=_NOW,
        source=SnapshotSource.TRIGGER_CELL,
        notebook_path="proj/nb.ipynb",
        state=JobState.PERSISTED,
        run_outcome=RunOutcome.ERROR,
        snapshot_id=SnapshotId("snap-1"),
        commit_hash=None,
        commit_url=None,
        directory_name="dir-1",
        directory_url=RemoteUrl("https://labarchives.test/dir-1"),
        meta_page_id="meta-1",
        meta_page_name="00 Metadata",
        page_count=3,
        error_code=None,
        error_message=None,
        display_message="Snapshot saved.",
    )
    payload = serialize_activity(record)
    assert payload["jobId"] == "job-1"
    assert payload["submittedAt"] == _NOW.isoformat()
    assert payload["state"] == "persisted"
    assert payload["runOutcome"] == "error"
    assert payload["directoryUrl"] == "https://labarchives.test/dir-1"
    assert payload["pageCount"] == 3
    assert payload["commitHash"] is None
    assert payload["displayMessage"] == "Snapshot saved."


# --- preview (C-CONFIG-02, C-CONFIG-11) matching the frontend schema ---


def test_preview_serializes_to_frontend_shape() -> None:
    plan = CapturePlan(
        artifacts=(
            PlannedArtifact(kind=ArtifactKind.NOTEBOOK, summary="Notebook"),
            PlannedArtifact(kind=ArtifactKind.FIGURE, summary="2 figures"),
        ),
        target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
            root_path=LabArchivesRootPath("Notebook Log/a@b.org"),
        ),
        tags=("baseline",),
        run_label="run-1",
    )
    provenance = {
        "target_notebook": ConfigLayer.INFERRED,
        "target_root_path": ConfigLayer.INFERRED,
        "commit_mode": ConfigLayer.USER,
    }
    payload = serialize_preview(
        plan=plan, provenance=provenance, generated_at=_NOW, source="frontend"
    )
    assert payload["generatedAt"] == _NOW.isoformat()
    assert payload["source"] == "frontend"
    assert payload["runLabel"] == "run-1"
    assert payload["tags"] == ["baseline"]
    assert payload["artifacts"] == [
        {"kind": "notebook", "summary": "Notebook"},
        {"kind": "figure", "summary": "2 figures"},
    ]
    assert payload["target"] == {
        "notebookName": "Jupyter Snapshots",
        "rootPath": "Notebook Log/a@b.org",
    }
    # provenance keys are camelCased to match the frontend reader (C-CONFIG-11)
    assert payload["provenance"] == {
        "targetNotebook": "inferred",
        "targetRootPath": "inferred",
        "commitMode": "user",
    }

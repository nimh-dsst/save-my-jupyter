from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from save_my_jupyter.adapters.activity_sqlite import SqliteActivityStore
from save_my_jupyter.application.snapshot.admission import SnapshotAdmission
from save_my_jupyter.application.snapshot.coordinator import SnapshotCoordinator
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.queue import Accepted, Coalesced, Rejected
from save_my_jupyter.domain.requests import (
    NotebookContext,
    RequestedMetadata,
    SnapshotRequest,
)
from save_my_jupyter.domain.types import CellId, DocumentId, NotebookPath, SnapshotId
from save_my_jupyter.worker.pool import WorkerPool

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


class _FrozenClock:
    def now(self) -> datetime:
        return _NOW


def _request(
    *,
    source: SnapshotSource = SnapshotSource.MANUAL,
    triggering: str | None = None,
    tags: tuple[str, ...] = (),
) -> SnapshotRequest:
    return SnapshotRequest(
        source=source,
        notebook_context=NotebookContext(
            notebook_path=NotebookPath("analysis/nb.ipynb"),
            notebook_name="nb.ipynb",
            document_id=DocumentId("doc-1"),
            triggering_cell_id=CellId(triggering) if triggering else None,
            triggered_cell_ids=(CellId(triggering),) if triggering else (),
        ),
        metadata=RequestedMetadata(tags=tags),
    )


def _persisted(job_id: str) -> ActivityRecord:
    return ActivityRecord(
        job_id=job_id,
        submitted_at=_NOW,
        completed_at=_NOW,
        source=SnapshotSource.MANUAL,
        notebook_path="analysis/nb.ipynb",
        state=JobState.PERSISTED,
        run_outcome=RunOutcome.SUCCESS,
        snapshot_id=SnapshotId("snap-1"),
        commit_hash=None,
        commit_url=None,
        directory_name="dir-1",
        directory_url=None,
        meta_page_id="meta-1",
        meta_page_name="00 Metadata",
        page_count=2,
        error_code=None,
        error_message=None,
        display_message="Snapshot saved. Job " + job_id + ".",
    )


def _coordinator(
    tmp_path: Path,
    *,
    pipeline: Callable[[str, SnapshotRequest], ActivityRecord] | None = None,
    pool: WorkerPool,
    admission: SnapshotAdmission,
) -> SnapshotCoordinator:
    store = SqliteActivityStore(tmp_path / "activity.sqlite")

    def default_pipeline(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        record = _persisted(job_id)
        store.save(record)
        return record

    return SnapshotCoordinator(
        admission=admission,
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=pipeline or default_pipeline,
    )


def test_accepted_manual_runs_pipeline_and_records_persisted(tmp_path: Path) -> None:
    pool = WorkerPool()
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    ran: list[str] = []

    def pipeline(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        ran.append(job_id)
        record = _persisted(job_id)
        store.save(record)
        return record

    coordinator = SnapshotCoordinator(
        admission=SnapshotAdmission(_FrozenClock()),
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=pipeline,
    )
    try:
        decision = coordinator.submit(job_id="job-1", request=_request())
        pool.join()
    finally:
        pool.shutdown()

    assert isinstance(decision, Accepted)
    assert ran == ["job-1"]
    stored = store.get("job-1")
    assert stored is not None
    assert stored.state is JobState.PERSISTED


def test_duplicate_trigger_run_is_rejected_after_completion(tmp_path: Path) -> None:
    pool = WorkerPool()
    admission = SnapshotAdmission(_FrozenClock())
    coordinator = _coordinator(tmp_path, pool=pool, admission=admission)
    try:
        first = coordinator.submit(
            job_id="job-1",
            request=_request(source=SnapshotSource.TRIGGER_CELL, triggering="cell-1"),
        )
        pool.join()
        second = coordinator.submit(
            job_id="job-2",
            request=_request(source=SnapshotSource.TRIGGER_CELL, triggering="cell-1"),
        )
    finally:
        pool.shutdown()

    assert isinstance(first, Accepted)
    assert isinstance(second, Rejected)
    assert second.reason_code == "duplicate_run"


def test_concurrent_trigger_with_same_fingerprint_coalesces(tmp_path: Path) -> None:
    # Hold the pipeline so the first job stays in-flight while the second arrives.
    import threading

    pool = WorkerPool()
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    release = threading.Event()

    def pipeline(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        release.wait(timeout=5)
        record = replace(_persisted(job_id), notebook_path="repo/relative.ipynb")
        store.save(record)
        return record

    admission = SnapshotAdmission(_FrozenClock())
    coordinator = SnapshotCoordinator(
        admission=admission,
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=pipeline,
    )
    try:
        first = coordinator.submit(
            job_id="job-1",
            request=_request(source=SnapshotSource.TRIGGER_CELL, triggering="cell-1"),
        )
        second = coordinator.submit(
            job_id="job-2",
            request=_request(source=SnapshotSource.TRIGGER_CELL, triggering="cell-1"),
        )
        release.set()
        pool.join()
    finally:
        release.set()
        pool.shutdown()

    assert isinstance(first, Accepted)
    assert isinstance(second, Coalesced)
    assert second.coalesced_into == "job-1"
    alias = store.get("job-2")
    assert alias is not None
    assert alias.state is JobState.PERSISTED
    assert alias.snapshot_id == SnapshotId("snap-1")
    assert alias.notebook_path == "repo/relative.ipynb"
    assert alias.display_message == "Snapshot saved. Job job-2."


def test_concurrent_trigger_with_different_tags_does_not_coalesce(
    tmp_path: Path,
) -> None:
    import threading

    pool = WorkerPool()
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    release = threading.Event()

    def pipeline(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        release.wait(timeout=5)
        record = _persisted(job_id)
        store.save(record)
        return record

    admission = SnapshotAdmission(_FrozenClock())
    coordinator = SnapshotCoordinator(
        admission=admission,
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=pipeline,
    )
    try:
        first = coordinator.submit(
            job_id="job-1",
            request=_request(
                source=SnapshotSource.TRIGGER_CELL,
                triggering="cell-1",
                tags=("baseline",),
            ),
        )
        second = coordinator.submit(
            job_id="job-2",
            request=_request(
                source=SnapshotSource.TRIGGER_CELL,
                triggering="cell-1",
                tags=("baseline", "qc"),
            ),
        )
        release.set()
        pool.join()
    finally:
        release.set()
        pool.shutdown()

    assert isinstance(first, Accepted)
    assert isinstance(second, Accepted)


def test_coalesced_job_id_records_same_failure_when_original_fails(
    tmp_path: Path,
) -> None:
    import threading

    pool = WorkerPool()
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    release = threading.Event()

    def pipeline(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        release.wait(timeout=5)
        raise SnapshotError(
            "LabArchives session expired.", code="labarchives_session_expired"
        )

    admission = SnapshotAdmission(_FrozenClock())
    coordinator = SnapshotCoordinator(
        admission=admission,
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=pipeline,
    )
    try:
        first = coordinator.submit(
            job_id="job-1",
            request=_request(source=SnapshotSource.TRIGGER_CELL, triggering="cell-1"),
        )
        second = coordinator.submit(
            job_id="job-2",
            request=_request(source=SnapshotSource.TRIGGER_CELL, triggering="cell-1"),
        )
        release.set()
        pool.join()
    finally:
        release.set()
        pool.shutdown()

    assert isinstance(first, Accepted)
    assert isinstance(second, Coalesced)
    failed = store.get("job-2")
    assert failed is not None
    assert failed.state is JobState.FAILED
    assert failed.error_code == "labarchives_session_expired"
    assert failed.display_message == "LabArchives session expired."


def test_failing_pipeline_records_failure_and_unsticks_queue(tmp_path: Path) -> None:
    pool = WorkerPool()
    store = SqliteActivityStore(tmp_path / "activity.sqlite")

    def boom(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        raise RuntimeError("kaboom")

    admission = SnapshotAdmission(_FrozenClock())
    coordinator = SnapshotCoordinator(
        admission=admission,
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=boom,
    )
    try:
        coordinator.submit(job_id="job-1", request=_request())
        pool.join()
        # queue unsticks: a second manual submission is still accepted
        second = coordinator.submit(job_id="job-2", request=_request())
        pool.join()
    finally:
        pool.shutdown()

    failed = store.get("job-1")
    assert failed is not None
    assert failed.state is JobState.FAILED
    assert isinstance(second, Accepted)


def test_structured_pipeline_error_is_preserved(tmp_path: Path) -> None:
    pool = WorkerPool()
    store = SqliteActivityStore(tmp_path / "activity.sqlite")

    def fail_with_code(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        raise SnapshotError(
            "Watched file is too large.", code="watched_file_artifact_too_large"
        )

    coordinator = SnapshotCoordinator(
        admission=SnapshotAdmission(_FrozenClock()),
        activity=store,
        clock=_FrozenClock(),
        enqueue=pool.submit,
        pipeline=fail_with_code,
    )
    try:
        coordinator.submit(job_id="job-1", request=_request())
        pool.join()
    finally:
        pool.shutdown()

    failed = store.get("job-1")
    assert failed is not None
    assert failed.state is JobState.FAILED
    assert failed.error_code == "watched_file_artifact_too_large"
    assert failed.display_message == "Watched file is too large."

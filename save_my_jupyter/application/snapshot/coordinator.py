"""Snapshot coordinator (target TRIGGER/QUEUE/CONFIRM). Turns a submitted
request into an admission decision and, when admitted, records the queued row
and enqueues the execution pipeline on the worker. The pool's submit and the
execution pipeline are injected callables, so this stays in the application
layer (no worker or IO-library import)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from save_my_jupyter.application.snapshot.fingerprint import compute_run_fingerprint
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.queue import Accepted

if TYPE_CHECKING:
    from save_my_jupyter.application.snapshot.admission import SnapshotAdmission
    from save_my_jupyter.domain.queue import AdmissionDecision
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.domain.types import RunFingerprint
    from save_my_jupyter.ports import ActivityStore, Clock

_Pipeline = Callable[[str, "SnapshotRequest"], ActivityRecord]
_Enqueue = Callable[[str, Callable[[], None]], None]


class SnapshotCoordinator:
    def __init__(
        self,
        *,
        admission: SnapshotAdmission,
        activity: ActivityStore,
        clock: Clock,
        enqueue: _Enqueue,
        pipeline: _Pipeline,
    ) -> None:
        self._admission = admission
        self._activity = activity
        self._clock = clock
        self._enqueue = enqueue
        self._pipeline = pipeline

    def submit(self, *, job_id: str, request: SnapshotRequest) -> AdmissionDecision:
        notebook_key = _notebook_key(request)
        decision = self._admission.admit(
            notebook_key=notebook_key,
            source=request.source,
            fingerprint=self._fingerprint(request),
            job_id=job_id,
        )
        if isinstance(decision, Accepted):
            self._activity.save(self._queued_record(job_id, request))
            self._enqueue(notebook_key, lambda: self._execute(job_id, request))
        return decision

    def _execute(self, job_id: str, request: SnapshotRequest) -> None:
        # Runs on a worker thread; must never raise (the pool does not catch).
        try:
            record = self._pipeline(job_id, request)
            succeeded = record.state is JobState.PERSISTED
        except Exception:
            self._activity.save(self._failed_record(job_id, request))
            succeeded = False
        self._admission.complete(job_id, succeeded=succeeded)

    def _fingerprint(self, request: SnapshotRequest) -> RunFingerprint:
        context = request.notebook_context
        return compute_run_fingerprint(
            notebook_key=_notebook_key(request),
            document_id=context.document_id,
            kernel_id=context.kernel_id,
            triggered_cell_ids=list(context.triggered_cell_ids),
            execution_count=context.cell_execution_count,
        )

    def _queued_record(self, job_id: str, request: SnapshotRequest) -> ActivityRecord:
        return _record(
            job_id=job_id,
            request=request,
            submitted_at=self._clock.now(),
            state=JobState.QUEUED,
            completed_at=None,
            display_message="Snapshot queued.",
        )

    def _failed_record(self, job_id: str, request: SnapshotRequest) -> ActivityRecord:
        return _record(
            job_id=job_id,
            request=request,
            submitted_at=self._clock.now(),
            state=JobState.FAILED,
            completed_at=self._clock.now(),
            display_message="Unable to save the snapshot.",
            error_code="snapshot_pipeline_failed",
            error_message="The snapshot pipeline failed unexpectedly.",
        )


def _notebook_key(request: SnapshotRequest) -> str:
    context = request.notebook_context
    return str(context.document_id or context.notebook_path)


def _record(
    *,
    job_id: str,
    request: SnapshotRequest,
    submitted_at: datetime,
    state: JobState,
    completed_at: datetime | None,
    display_message: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ActivityRecord:
    return ActivityRecord(
        job_id=job_id,
        submitted_at=submitted_at,
        completed_at=completed_at,
        source=request.source,
        notebook_path=str(request.notebook_context.notebook_path),
        state=state,
        run_outcome=RunOutcome.NOT_APPLICABLE,
        snapshot_id=None,
        commit_hash=None,
        commit_url=None,
        directory_name=None,
        directory_url=None,
        meta_page_id=None,
        meta_page_name=None,
        page_count=None,
        error_code=error_code,
        error_message=error_message,
        display_message=display_message,
    )

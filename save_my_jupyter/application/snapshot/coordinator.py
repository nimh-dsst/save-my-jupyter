"""Snapshot coordinator (target TRIGGER/QUEUE/CONFIRM). Turns a submitted
request into an admission decision and, when admitted, records the queued row
and enqueues the execution pipeline on the worker. The pool's submit and the
execution pipeline are injected callables, so this stays in the application
layer (no worker or IO-library import)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from save_my_jupyter.application.activity.transitions import is_terminal
from save_my_jupyter.application.confirm.messages import build_display_message
from save_my_jupyter.application.snapshot.fingerprint import compute_run_fingerprint
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.queue import Accepted, Coalesced

if TYPE_CHECKING:
    from save_my_jupyter.application.snapshot.admission import SnapshotAdmission
    from save_my_jupyter.domain.queue import AdmissionDecision
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.domain.types import RunFingerprint
    from save_my_jupyter.ports import ActivityStore, Clock

_Pipeline = Callable[[str, "SnapshotRequest"], ActivityRecord]
_Enqueue = Callable[[str, Callable[[], None]], None]
_CoalescedAlias = tuple[str, "SnapshotRequest"]


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
        self._coalesced_aliases: dict[str, list[_CoalescedAlias]] = {}
        self._alias_lock = threading.Lock()

    def submit(self, *, job_id: str, request: SnapshotRequest) -> AdmissionDecision:
        notebook_key = _notebook_key(request)
        decision = self._admission.admit(
            notebook_key=notebook_key,
            source=request.source,
            fingerprint=self._fingerprint(request),
            job_id=job_id,
        )
        if isinstance(decision, Accepted):
            try:
                self._activity.save(self._queued_record(job_id, request))
                self._enqueue(notebook_key, lambda: self._execute(job_id, request))
            except Exception as exc:
                self._admission.complete(job_id, succeeded=False)
                if isinstance(exc, SnapshotError):
                    self._save_best_effort(
                        self._failed_record(
                            job_id,
                            request,
                            error_code=exc.code,
                            error_message=str(exc),
                            display_message=str(exc),
                        )
                    )
                    raise
                error = SnapshotError(
                    "Unable to queue the snapshot.",
                    code="snapshot_queue_failed",
                )
                self._save_best_effort(
                    self._failed_record(
                        job_id,
                        request,
                        error_code=error.code,
                        error_message=str(error),
                        display_message=str(error),
                    )
                )
                raise error from exc
        elif isinstance(decision, Coalesced):
            try:
                self._activity.save(self._queued_record(job_id, request))
                self._register_coalesced_alias(
                    original_job_id=decision.coalesced_into,
                    alias_job_id=job_id,
                    request=request,
                )
            except Exception as exc:
                error = SnapshotError(
                    "Unable to queue the snapshot.",
                    code="snapshot_queue_failed",
                )
                self._save_best_effort(
                    self._failed_record(
                        job_id,
                        request,
                        error_code=error.code,
                        error_message=str(error),
                        display_message=str(error),
                    )
                )
                raise error from exc
        return decision

    def _execute(self, job_id: str, request: SnapshotRequest) -> None:
        # Runs on a worker thread; must never raise (the pool does not catch).
        final_record: ActivityRecord | None = None
        succeeded = False
        try:
            self._save_best_effort(self._running_record(job_id, request))
            record = self._pipeline(job_id, request)
            self._save_best_effort(record)
            final_record = record
            succeeded = record.state is JobState.PERSISTED
        except SnapshotError as exc:
            final_record = self._failed_record(
                job_id,
                request,
                error_code=exc.code,
                error_message=str(exc),
                display_message=str(exc),
            )
            self._save_best_effort(final_record)
        except Exception:
            final_record = self._failed_record(job_id, request)
            self._save_best_effort(final_record)
        finally:
            if final_record is not None:
                self._complete_coalesced_aliases(job_id, final_record)
            self._admission.complete(job_id, succeeded=succeeded)

    def _fingerprint(self, request: SnapshotRequest) -> RunFingerprint:
        context = request.notebook_context
        return compute_run_fingerprint(
            notebook_key=_notebook_key(request),
            document_id=context.document_id,
            kernel_id=context.kernel_id,
            triggered_cell_ids=list(context.triggered_cell_ids),
            execution_count=context.cell_execution_count,
            tags=request.metadata.tags,
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

    def _running_record(self, job_id: str, request: SnapshotRequest) -> ActivityRecord:
        return _record(
            job_id=job_id,
            request=request,
            submitted_at=self._submitted_at(job_id),
            state=JobState.RUNNING,
            completed_at=None,
            display_message=build_display_message(
                state=JobState.RUNNING,
                source=request.source,
                job_id=job_id,
            ),
        )

    def _failed_record(
        self,
        job_id: str,
        request: SnapshotRequest,
        *,
        error_code: str = "snapshot_pipeline_failed",
        error_message: str = "The snapshot pipeline failed unexpectedly.",
        display_message: str = "Unable to save the snapshot.",
    ) -> ActivityRecord:
        return _record(
            job_id=job_id,
            request=request,
            submitted_at=self._clock.now(),
            state=JobState.FAILED,
            completed_at=self._clock.now(),
            display_message=display_message,
            error_code=error_code,
            error_message=error_message,
        )

    def _submitted_at(self, job_id: str) -> datetime:
        try:
            existing = self._activity.get(job_id)
        except Exception:
            existing = None
        return existing.submitted_at if existing is not None else self._clock.now()

    def _save_best_effort(self, record: ActivityRecord) -> None:
        try:
            self._activity.save(record)
        except Exception:
            return

    def _register_coalesced_alias(
        self,
        *,
        original_job_id: str,
        alias_job_id: str,
        request: SnapshotRequest,
    ) -> None:
        alias_final_record: ActivityRecord | None = None
        with self._alias_lock:
            final_record = self._activity.get(original_job_id)
            if final_record is not None and is_terminal(final_record.state):
                alias_final_record = final_record
            else:
                self._coalesced_aliases.setdefault(original_job_id, []).append(
                    (alias_job_id, request)
                )
                return
        if alias_final_record is None:
            return
        self._save_alias_record(
            original_job_id=original_job_id,
            final_record=alias_final_record,
            alias_job_id=alias_job_id,
            request=request,
        )

    def _complete_coalesced_aliases(
        self, original_job_id: str, final_record: ActivityRecord
    ) -> None:
        with self._alias_lock:
            aliases = tuple(self._coalesced_aliases.pop(original_job_id, ()))
        for alias_job_id, request in aliases:
            self._save_alias_record(
                original_job_id=original_job_id,
                final_record=final_record,
                alias_job_id=alias_job_id,
                request=request,
            )

    def _save_alias_record(
        self,
        *,
        original_job_id: str,
        final_record: ActivityRecord,
        alias_job_id: str,
        request: SnapshotRequest,
    ) -> None:
        queued_alias = self._activity.get(alias_job_id)
        submitted_at = (
            queued_alias.submitted_at
            if queued_alias is not None
            else final_record.submitted_at
        )
        self._save_best_effort(self._running_record(alias_job_id, request))
        self._save_best_effort(
            replace(
                final_record,
                job_id=alias_job_id,
                submitted_at=submitted_at,
                source=request.source,
                display_message=_alias_display_message(
                    final_record.display_message,
                    original_job_id=original_job_id,
                    alias_job_id=alias_job_id,
                ),
            )
        )


def _notebook_key(request: SnapshotRequest) -> str:
    context = request.notebook_context
    return str(context.document_id or context.notebook_path)


def _alias_display_message(
    display_message: str, *, original_job_id: str, alias_job_id: str
) -> str:
    return display_message.replace(f"Job {original_job_id}.", f"Job {alias_job_id}.", 1)


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

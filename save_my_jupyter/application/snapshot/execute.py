"""Snapshot execution orchestrator (target DELIVER/CONFIRM). The use-case the
worker runs after admission: mark the job running, deliver the prepared bundle
through the Delivery port, then record the terminal Activity row with the
canonical display message. Side effects happen only through injected ports; the
bundle is built purely upstream (build.py)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from save_my_jupyter.application.confirm.messages import build_display_message
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import JobState, RunOutcome

if TYPE_CHECKING:
    from save_my_jupyter.domain.delivery import DeliveryReceipt, SnapshotBundle
    from save_my_jupyter.domain.types import CommitHash, RemoteUrl, SnapshotId
    from save_my_jupyter.ports import ActivityStore, Clock, Delivery


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotContext:
    """Per-job facts the Activity row needs that are not in the bundle itself."""

    job_id: str
    submitted_at: datetime
    source: SnapshotSource
    notebook_path: str
    run_outcome: RunOutcome
    snapshot_id: SnapshotId
    commit_hash: CommitHash | None = None
    commit_status: str = "none"
    commit_url: RemoteUrl | None = None


def execute_snapshot(
    *,
    bundle: SnapshotBundle,
    context: SnapshotContext,
    delivery: Delivery,
    activity: ActivityStore,
    clock: Clock,
) -> ActivityRecord:
    activity.save(_running_record(context))
    try:
        receipt = delivery.deliver(bundle)
    except SnapshotError as exc:
        failed = _failed_record(context, exc, completed_at=clock.now())
        activity.save(failed)
        return failed
    persisted = _persisted_record(context, receipt, completed_at=clock.now())
    activity.save(persisted)
    return persisted


def _running_record(context: SnapshotContext) -> ActivityRecord:
    return _base_record(
        context,
        state=JobState.RUNNING,
        completed_at=None,
        display_message=build_display_message(
            state=JobState.RUNNING, source=context.source, job_id=context.job_id
        ),
    )


def _failed_record(
    context: SnapshotContext, error: SnapshotError, *, completed_at: datetime
) -> ActivityRecord:
    return _base_record(
        context,
        state=JobState.FAILED,
        completed_at=completed_at,
        error_code=error.code,
        error_message=str(error),
        display_message=build_display_message(
            state=JobState.FAILED,
            source=context.source,
            job_id=context.job_id,
            error_message=str(error),
        ),
    )


def _persisted_record(
    context: SnapshotContext, receipt: DeliveryReceipt, *, completed_at: datetime
) -> ActivityRecord:
    return _base_record(
        context,
        state=JobState.PERSISTED,
        completed_at=completed_at,
        directory_name=receipt.directory_name,
        directory_url=receipt.url,
        meta_page_id=receipt.meta_page_id,
        meta_page_name=receipt.meta_page_name,
        page_count=receipt.page_count,
        display_message=build_display_message(
            state=JobState.PERSISTED,
            source=context.source,
            job_id=context.job_id,
            snapshot_id=context.snapshot_id,
            commit_hash=context.commit_hash,
            commit_status=context.commit_status,
            commit_url=context.commit_url,
            directory_url=receipt.url,
            meta_page_name=receipt.meta_page_name,
            meta_page_id=receipt.meta_page_id,
        ),
    )


def _base_record(
    context: SnapshotContext,
    *,
    state: JobState,
    completed_at: datetime | None,
    display_message: str,
    directory_name: str | None = None,
    directory_url: RemoteUrl | None = None,
    meta_page_id: str | None = None,
    meta_page_name: str | None = None,
    page_count: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ActivityRecord:
    return ActivityRecord(
        job_id=context.job_id,
        submitted_at=context.submitted_at,
        completed_at=completed_at,
        source=context.source,
        notebook_path=context.notebook_path,
        state=state,
        run_outcome=context.run_outcome,
        snapshot_id=context.snapshot_id,
        commit_hash=context.commit_hash,
        commit_url=context.commit_url,
        directory_name=directory_name,
        directory_url=directory_url,
        meta_page_id=meta_page_id,
        meta_page_name=meta_page_name,
        page_count=page_count,
        error_code=error_code,
        error_message=error_message,
        display_message=display_message,
    )

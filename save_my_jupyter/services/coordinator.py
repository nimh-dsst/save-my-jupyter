from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

from save_my_jupyter.domain import (
    NotebookContext,
    ResolvedSnapshotPlan,
    RunFingerprint,
    SnapshotAccepted,
    SnapshotRejected,
)

_MAX_PENDING_SNAPSHOTS_PER_NOTEBOOK = 5


@dataclass(slots=True)
class NotebookSnapshotQueue:
    notebook_key: str
    pending_jobs: deque[ResolvedSnapshotPlan] = field(default_factory=deque)
    running_job: ResolvedSnapshotPlan | None = None
    recent_run_fingerprints: set[RunFingerprint] = field(default_factory=set)

    def enqueue(self, plan: ResolvedSnapshotPlan) -> None:
        self.pending_jobs.append(plan)

    def start_next(self) -> ResolvedSnapshotPlan | None:
        if self.running_job is not None or not self.pending_jobs:
            return None
        self.running_job = self.pending_jobs.popleft()
        return self.running_job

    def mark_complete(self, run_fingerprint: RunFingerprint) -> None:
        self.mark_finished(run_fingerprint, record_run=True)

    def mark_finished(
        self,
        run_fingerprint: RunFingerprint,
        *,
        record_run: bool,
    ) -> None:
        if record_run:
            self.recent_run_fingerprints.add(run_fingerprint)
        self.running_job = None

    def has_seen_run(self, run_fingerprint: RunFingerprint) -> bool:
        return run_fingerprint in self.recent_run_fingerprints


class SnapshotCoordinator:
    def __init__(self) -> None:
        self.queues: dict[str, NotebookSnapshotQueue] = {}

    def submit(self, plan: ResolvedSnapshotPlan) -> SnapshotAccepted | SnapshotRejected:
        queue = self.get_or_create_queue(
            self.build_notebook_key(plan.request.notebook_context)
        )
        if plan.request.source.value != "manual" and queue.has_seen_run(
            plan.run_fingerprint
        ):
            return SnapshotRejected(
                reason_code="duplicate_run",
                message="A snapshot already exists for this run.",
            )

        if self.coalesce_trigger(queue, plan):
            return SnapshotAccepted(
                job_id=str(uuid4()),
                queue_position=len(queue.pending_jobs),
            )

        if len(queue.pending_jobs) >= _MAX_PENDING_SNAPSHOTS_PER_NOTEBOOK:
            return SnapshotRejected(
                reason_code="snapshot_queue_full",
                message=(
                    "Too many snapshots are already queued for this notebook. "
                    "Wait for the current save to finish before starting another."
                ),
            )

        queue.enqueue(plan)
        return SnapshotAccepted(
            job_id=str(uuid4()),
            queue_position=len(queue.pending_jobs),
        )

    def get_or_create_queue(self, notebook_key: str) -> NotebookSnapshotQueue:
        queue = self.queues.get(notebook_key)
        if queue is None:
            queue = NotebookSnapshotQueue(notebook_key=notebook_key)
            self.queues[notebook_key] = queue
        return queue

    def coalesce_trigger(
        self,
        queue: NotebookSnapshotQueue,
        plan: ResolvedSnapshotPlan,
    ) -> bool:
        if plan.request.source.value == "manual":
            return False

        if (
            queue.running_job is not None
            and queue.running_job.run_fingerprint == plan.run_fingerprint
        ):
            return True

        return any(
            pending_plan.run_fingerprint == plan.run_fingerprint
            for pending_plan in queue.pending_jobs
        )

    def build_notebook_key(self, context: NotebookContext) -> str:
        return str(context.document_id or context.notebook_path)

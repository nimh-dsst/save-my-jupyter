from __future__ import annotations

from typing import Protocol

from save_my_jupyter.domain.activity import ActivityRecord


class ActivityStore(Protocol):
    """Durable snapshot history (contracts C-QUEUE-06, C-STATE-01). Survives
    restarts; the dedupe cache does not."""

    def save(self, record: ActivityRecord) -> None:
        """Insert or replace a job's record, keyed by ``job_id``."""
        ...

    def get(self, job_id: str) -> ActivityRecord | None: ...

    def recent(self, limit: int) -> tuple[ActivityRecord, ...]:
        """Most recently submitted jobs first, capped at ``limit``."""
        ...

    def abandon_inflight(self) -> int:
        """Startup reconciliation: mark every ``queued``/``running`` job
        ``abandoned`` and return how many were changed (contract C-QUEUE-05)."""
        ...

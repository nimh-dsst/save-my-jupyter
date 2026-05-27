"""Backend-authoritative queue admission and run dedupe (target TRIGGER/QUEUE,
contracts C-QUEUE-01/02/04). Frontend coalescing is a UX optimization only; the
guarantee that one run yields one snapshot lives here. State is in-memory and
resets on restart -- by design, a restart re-enables a previously deduped run
(contract C-QUEUE-06). The clock is injected so the dedupe TTL is testable."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.queue import (
    DUPLICATE_RUN_MESSAGE,
    QUEUE_FULL_MESSAGE,
    Accepted,
    AdmissionDecision,
    Coalesced,
    Rejected,
)

if TYPE_CHECKING:
    from save_my_jupyter.domain.types import RunFingerprint
    from save_my_jupyter.ports import Clock

_DEFAULT_MAX_PENDING = 5
_DEFAULT_DEDUPE_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class _JobInfo:
    notebook_key: str
    fingerprint: str
    source: SnapshotSource


class SnapshotAdmission:
    def __init__(
        self,
        clock: Clock,
        *,
        max_pending: int = _DEFAULT_MAX_PENDING,
        dedupe_ttl: timedelta = _DEFAULT_DEDUPE_TTL,
    ) -> None:
        self._clock = clock
        self._max_pending = max_pending
        self._dedupe_ttl = dedupe_ttl
        self._pending: dict[str, int] = {}
        self._active_fingerprints: dict[str, str] = {}
        self._completed_fingerprints: dict[str, datetime] = {}
        self._jobs: dict[str, _JobInfo] = {}
        self._lock = threading.Lock()

    def admit(
        self,
        *,
        notebook_key: str,
        source: SnapshotSource,
        fingerprint: RunFingerprint,
        job_id: str,
    ) -> AdmissionDecision:
        with self._lock:
            self._expire_completed()

            if source is SnapshotSource.TRIGGER_CELL:
                in_flight = self._active_fingerprints.get(fingerprint)
                if in_flight is not None:
                    return Coalesced(job_id=job_id, coalesced_into=in_flight)
                if fingerprint in self._completed_fingerprints:
                    return Rejected(
                        reason_code="duplicate_run", message=DUPLICATE_RUN_MESSAGE
                    )

            if self._pending.get(notebook_key, 0) >= self._max_pending:
                return Rejected(
                    reason_code="snapshot_queue_full", message=QUEUE_FULL_MESSAGE
                )

            self._pending[notebook_key] = self._pending.get(notebook_key, 0) + 1
            if source is SnapshotSource.TRIGGER_CELL:
                self._active_fingerprints[fingerprint] = job_id
            self._jobs[job_id] = _JobInfo(
                notebook_key=notebook_key, fingerprint=fingerprint, source=source
            )
            return Accepted(job_id=job_id)

    def complete(self, job_id: str, *, succeeded: bool) -> None:
        with self._lock:
            info = self._jobs.pop(job_id, None)
            if info is None:
                return
            remaining = self._pending.get(info.notebook_key, 0) - 1
            self._pending[info.notebook_key] = max(0, remaining)
            if info.source is SnapshotSource.TRIGGER_CELL:
                self._active_fingerprints.pop(info.fingerprint, None)
                # Only a successful run records its fingerprint; failures stay
                # retryable (contract C-QUEUE-04).
                if succeeded:
                    self._completed_fingerprints[info.fingerprint] = self._clock.now()

    def _expire_completed(self) -> None:
        cutoff = self._clock.now() - self._dedupe_ttl
        expired = [
            fingerprint
            for fingerprint, completed_at in self._completed_fingerprints.items()
            if completed_at < cutoff
        ]
        for fingerprint in expired:
            del self._completed_fingerprints[fingerprint]

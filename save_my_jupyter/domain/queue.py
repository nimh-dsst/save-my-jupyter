from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

# Fixed queue-time rejection messages (contracts C-QUEUE-01/02, C-FAIL-02).
DUPLICATE_RUN_MESSAGE = "A snapshot already exists for this run."
QUEUE_FULL_MESSAGE = (
    "Too many snapshots are already queued for this notebook. Wait for the "
    "current save to finish before starting another."
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Accepted:
    """Admitted as new work; the job id is enqueued."""

    job_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Coalesced:
    """Collapsed into an in-flight job with the same run fingerprint. The fresh
    job id is still returned so the client can correlate (contract C-QUEUE-02)."""

    job_id: str
    coalesced_into: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Rejected:
    reason_code: str
    message: str


AdmissionDecision: TypeAlias = Accepted | Coalesced | Rejected

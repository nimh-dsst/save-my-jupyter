from __future__ import annotations

from datetime import UTC, datetime, timedelta

from save_my_jupyter.application.snapshot.admission import SnapshotAdmission
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.queue import Accepted, Coalesced, Rejected
from save_my_jupyter.domain.types import RunFingerprint


class _MovableClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _trigger(
    admission: SnapshotAdmission,
    job_id: str,
    *,
    fingerprint: str = "fp-1",
    notebook: str = "doc-1",
) -> object:
    return admission.admit(
        notebook_key=notebook,
        source=SnapshotSource.TRIGGER_CELL,
        fingerprint=RunFingerprint(fingerprint),
        job_id=job_id,
    )


def _manual(
    admission: SnapshotAdmission, job_id: str, *, notebook: str = "doc-1"
) -> object:
    return admission.admit(
        notebook_key=notebook,
        source=SnapshotSource.MANUAL,
        fingerprint=RunFingerprint("fp-manual"),
        job_id=job_id,
    )


# --- trigger dedupe (C-QUEUE-02) ---


def test_trigger_with_inflight_fingerprint_coalesces() -> None:
    admission = SnapshotAdmission(_MovableClock())
    first = _trigger(admission, "job-1")
    second = _trigger(admission, "job-2")
    assert isinstance(first, Accepted)
    assert isinstance(second, Coalesced)
    assert second.job_id == "job-2"
    assert second.coalesced_into == "job-1"


def test_trigger_matching_completed_run_is_rejected_duplicate() -> None:
    admission = SnapshotAdmission(_MovableClock())
    _trigger(admission, "job-1")
    admission.complete("job-1", succeeded=True)
    again = _trigger(admission, "job-2")
    assert isinstance(again, Rejected)
    assert again.reason_code == "duplicate_run"
    assert again.message == "A snapshot already exists for this run."


def test_failed_trigger_run_does_not_record_fingerprint() -> None:
    # C-QUEUE-04: a failed run unsticks, so the same trigger can be retried.
    admission = SnapshotAdmission(_MovableClock())
    _trigger(admission, "job-1")
    admission.complete("job-1", succeeded=False)
    retry = _trigger(admission, "job-2")
    assert isinstance(retry, Accepted)


def test_completed_fingerprint_expires_after_ttl() -> None:
    clock = _MovableClock()
    admission = SnapshotAdmission(clock, dedupe_ttl=timedelta(minutes=10))
    _trigger(admission, "job-1")
    admission.complete("job-1", succeeded=True)
    clock.advance(timedelta(minutes=11))
    assert isinstance(_trigger(admission, "job-2"), Accepted)


# --- manual never dedupes (C-QUEUE-02, C-SNAP-01) ---


def test_manual_submissions_never_dedupe() -> None:
    admission = SnapshotAdmission(_MovableClock())
    first = _manual(admission, "job-1")
    second = _manual(admission, "job-2")
    assert isinstance(first, Accepted)
    assert isinstance(second, Accepted)


# --- per-notebook queue cap (C-QUEUE-01) ---


def test_sixth_pending_snapshot_is_rejected_queue_full() -> None:
    admission = SnapshotAdmission(_MovableClock())
    for index in range(5):
        assert isinstance(_manual(admission, f"job-{index}"), Accepted)
    sixth = _manual(admission, "job-5")
    assert isinstance(sixth, Rejected)
    assert sixth.reason_code == "snapshot_queue_full"
    assert "Too many snapshots" in sixth.message


def test_queue_unsticks_when_a_job_completes() -> None:
    admission = SnapshotAdmission(_MovableClock())
    for index in range(5):
        _manual(admission, f"job-{index}")
    admission.complete("job-0", succeeded=True)
    assert isinstance(_manual(admission, "job-5"), Accepted)


def test_queue_cap_is_per_notebook() -> None:
    admission = SnapshotAdmission(_MovableClock())
    for index in range(5):
        _manual(admission, f"a-{index}", notebook="doc-a")
    # A different notebook is unaffected by doc-a being full.
    assert isinstance(_manual(admission, "b-0", notebook="doc-b"), Accepted)


def test_coalesced_trigger_does_not_consume_queue_capacity() -> None:
    admission = SnapshotAdmission(_MovableClock())
    _trigger(admission, "job-1")  # 1 pending
    for _ in range(10):
        # repeated identical-run submissions coalesce, never filling the queue
        assert isinstance(_trigger(admission, "dup"), Coalesced)

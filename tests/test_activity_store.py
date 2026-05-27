from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.activity_sqlite import SqliteActivityStore
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.types import CommitHash, RemoteUrl, SnapshotId

if TYPE_CHECKING:
    from save_my_jupyter.ports import ActivityStore

_BASE = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


def _record(job_id: str, *, state: JobState, submitted: datetime) -> ActivityRecord:
    return ActivityRecord(
        job_id=job_id,
        submitted_at=submitted,
        completed_at=None,
        source=SnapshotSource.MANUAL,
        notebook_path="analysis/nb.ipynb",
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
        error_code=None,
        error_message=None,
        display_message="Snapshot queued.",
    )


def _store(tmp_path: Path) -> SqliteActivityStore:
    return SqliteActivityStore(tmp_path / "activity.sqlite")


def test_save_and_get_round_trips_all_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = ActivityRecord(
        job_id="job-1",
        submitted_at=_BASE,
        completed_at=_BASE + timedelta(seconds=3),
        source=SnapshotSource.TRIGGER_CELL,
        notebook_path="analysis/nb.ipynb",
        state=JobState.PERSISTED,
        run_outcome=RunOutcome.ERROR,
        snapshot_id=SnapshotId("snap-1"),
        commit_hash=CommitHash("abcdef1234567890"),
        commit_url=RemoteUrl("https://git.example/c/abc"),
        directory_name="dir-1",
        directory_url=RemoteUrl("https://labarchives.test/dir-1"),
        meta_page_id="meta-1",
        meta_page_name="00 Metadata",
        page_count=3,
        error_code=None,
        error_message=None,
        display_message="Snapshot saved. Job job-1.",
    )
    store.save(record)
    assert store.get("job-1") == record


def test_get_unknown_job_returns_none(tmp_path: Path) -> None:
    assert _store(tmp_path).get("missing") is None


def test_save_replaces_existing_job(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(_record("job-1", state=JobState.QUEUED, submitted=_BASE))
    store.save(_record("job-1", state=JobState.RUNNING, submitted=_BASE))
    fetched = store.get("job-1")
    assert fetched is not None
    assert fetched.state is JobState.RUNNING


def test_recent_returns_newest_first_capped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for offset in range(5):
        store.save(
            _record(
                f"job-{offset}",
                state=JobState.PERSISTED,
                submitted=_BASE + timedelta(minutes=offset),
            )
        )
    recent = store.recent(3)
    assert [r.job_id for r in recent] == ["job-4", "job-3", "job-2"]


def test_abandon_inflight_marks_only_pending_jobs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(_record("queued", state=JobState.QUEUED, submitted=_BASE))
    store.save(_record("running", state=JobState.RUNNING, submitted=_BASE))
    store.save(_record("done", state=JobState.PERSISTED, submitted=_BASE))

    changed = store.abandon_inflight()
    assert changed == 2

    queued = store.get("queued")
    running = store.get("running")
    done = store.get("done")
    assert queued is not None
    assert running is not None
    assert done is not None
    assert queued.state is JobState.ABANDONED
    assert running.state is JobState.ABANDONED
    assert done.state is JobState.PERSISTED


def test_state_survives_a_fresh_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "activity.sqlite"
    SqliteActivityStore(db_path).save(
        _record("job-1", state=JobState.PERSISTED, submitted=_BASE)
    )
    # A new store over the same file is what a server restart looks like.
    reopened = SqliteActivityStore(db_path).get("job-1")
    assert reopened is not None
    assert reopened.state is JobState.PERSISTED


def test_sqlite_store_satisfies_the_activity_store_port(tmp_path: Path) -> None:
    store: ActivityStore = _store(tmp_path)
    assert store is not None

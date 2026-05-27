"""SQLite-backed `ActivityStore` (target CONFIRM). Durable across restarts
(contracts C-QUEUE-06, C-STATE-01). WAL mode plus a fresh short-lived connection
per call keeps it safe to use from the multi-threaded worker pool without
sharing a connection across threads."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from save_my_jupyter.application.activity.transitions import can_transition
from save_my_jupyter.application.confirm.messages import build_display_message
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState, RunOutcome

_COLUMNS = (
    "job_id",
    "submitted_at",
    "completed_at",
    "source",
    "notebook_path",
    "state",
    "run_outcome",
    "snapshot_id",
    "commit_hash",
    "commit_url",
    "directory_name",
    "directory_url",
    "meta_page_id",
    "meta_page_name",
    "page_count",
    "error_code",
    "error_message",
    "display_message",
)
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS activity ("
    "job_id TEXT PRIMARY KEY, submitted_at TEXT NOT NULL, completed_at TEXT, "
    "source TEXT NOT NULL, notebook_path TEXT NOT NULL, state TEXT NOT NULL, "
    "run_outcome TEXT NOT NULL, snapshot_id TEXT, commit_hash TEXT, "
    "commit_url TEXT, directory_name TEXT, directory_url TEXT, meta_page_id TEXT, "
    "meta_page_name TEXT, page_count INTEGER, error_code TEXT, error_message TEXT, "
    "display_message TEXT NOT NULL)"
)


class SqliteActivityStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def save(self, record: ActivityRecord) -> None:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        statement = (
            f"INSERT OR REPLACE INTO activity ({', '.join(_COLUMNS)}) "
            f"VALUES ({placeholders})"
        )
        with closing(self._connect()) as conn:
            current = conn.execute(
                "SELECT state FROM activity WHERE job_id = ?", (record.job_id,)
            ).fetchone()
            if current is not None:
                current_state = JobState(current["state"])
                if current_state != record.state and not can_transition(
                    current_state, record.state
                ):
                    return
            conn.execute(statement, _to_row(record))
            conn.commit()

    def get(self, job_id: str) -> ActivityRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM activity WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def recent(self, limit: int) -> tuple[ActivityRecord, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM activity ORDER BY submitted_at DESC, job_id DESC "
                "LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(_from_row(row) for row in rows)

    def abandon_inflight(self) -> int:
        completed_at = datetime.now(UTC).isoformat()
        display_message = build_display_message(
            state=JobState.ABANDONED,
            source=SnapshotSource.MANUAL,
            job_id="",
        )
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE activity SET state = ?, completed_at = ?, display_message = ? "
                "WHERE state IN (?, ?)",
                (
                    JobState.ABANDONED.value,
                    completed_at,
                    display_message,
                    JobState.QUEUED.value,
                    JobState.RUNNING.value,
                ),
            )
            conn.commit()
            return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn


def _to_row(record: ActivityRecord) -> tuple[object, ...]:
    completed = record.completed_at.isoformat() if record.completed_at else None
    return (
        record.job_id,
        record.submitted_at.isoformat(),
        completed,
        record.source.value,
        record.notebook_path,
        record.state.value,
        record.run_outcome.value,
        record.snapshot_id,
        record.commit_hash,
        record.commit_url,
        record.directory_name,
        record.directory_url,
        record.meta_page_id,
        record.meta_page_name,
        record.page_count,
        record.error_code,
        record.error_message,
        record.display_message,
    )


def _from_row(row: sqlite3.Row) -> ActivityRecord:
    # NewType (str-based) and primitive columns come back as the right runtime
    # value already; only datetimes and enums need reconstruction.
    return ActivityRecord(
        job_id=row["job_id"],
        submitted_at=datetime.fromisoformat(row["submitted_at"]),
        completed_at=_optional_datetime(row["completed_at"]),
        source=SnapshotSource(row["source"]),
        notebook_path=row["notebook_path"],
        state=JobState(row["state"]),
        run_outcome=RunOutcome(row["run_outcome"]),
        snapshot_id=row["snapshot_id"],
        commit_hash=row["commit_hash"],
        commit_url=row["commit_url"],
        directory_name=row["directory_name"],
        directory_url=row["directory_url"],
        meta_page_id=row["meta_page_id"],
        meta_page_name=row["meta_page_name"],
        page_count=row["page_count"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        display_message=row["display_message"],
    )


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from save_my_jupyter.adapters.activity_sqlite import SqliteActivityStore
from save_my_jupyter.adapters.fake_delivery import FakeDelivery
from save_my_jupyter.application.snapshot.build import build_snapshot_bundle
from save_my_jupyter.application.snapshot.execute import (
    SnapshotContext,
    execute_snapshot,
)
from save_my_jupyter.domain.artifacts import NotebookPayload
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import (
    DeliveryReceipt,
    SnapshotBundle,
    SnapshotMetadata,
)
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.types import (
    CommitHash,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    SnapshotId,
)

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


class _FrozenClock:
    def now(self) -> datetime:
        return _NOW


class _FailingDelivery:
    def deliver(self, bundle: SnapshotBundle) -> DeliveryReceipt:
        raise SnapshotError(
            "LabArchives write failed.",
            code="labarchives_write_failed",
            context={"directory": bundle.directory_name},
        )


def _bundle(snapshot_id: str = "snap-1") -> SnapshotBundle:
    metadata = SnapshotMetadata(
        notebook_name="nb.ipynb",
        notebook_path="proj/nb.ipynb",
        source=SnapshotSource.MANUAL,
        run_outcome=RunOutcome.NOT_APPLICABLE,
        snapshot_id=SnapshotId(snapshot_id),
        run_fingerprint=None,
        trigger_cells=(),
        commit_hash=None,
        commit_status="none",
        commit_url=None,
        diff_included=False,
        extension_version="0.1.0",
        run_label=None,
        tags=(),
        notes=None,
        execution_summary="ok",
    )
    return build_snapshot_bundle(
        directory_name="dir-1",
        target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
            root_path=LabArchivesRootPath("Notebook Log"),
        ),
        metadata=metadata,
        notebook=NotebookPayload(filename="nb.ipynb", content=b"{}"),
    )


def _context(
    *,
    source: SnapshotSource = SnapshotSource.MANUAL,
    run_outcome: RunOutcome = RunOutcome.NOT_APPLICABLE,
    commit_hash: CommitHash | None = None,
    commit_status: str = "none",
) -> SnapshotContext:
    return SnapshotContext(
        job_id="job-1",
        submitted_at=_NOW,
        source=source,
        notebook_path="proj/nb.ipynb",
        run_outcome=run_outcome,
        snapshot_id=SnapshotId("snap-1"),
        commit_hash=commit_hash,
        commit_status=commit_status,
    )


def test_successful_delivery_records_persisted_with_references(tmp_path: Path) -> None:
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    delivery = FakeDelivery()

    result = execute_snapshot(
        bundle=_bundle(),
        context=_context(),
        delivery=delivery,
        activity=store,
        clock=_FrozenClock(),
    )

    assert result.state is JobState.PERSISTED
    assert result.completed_at == _NOW
    assert result.directory_name == "dir-1"
    assert result.directory_url is not None
    assert result.display_message.startswith("Snapshot saved.")
    assert result.display_message.endswith(f"LabArchives {result.directory_url}.")

    # the durable store reflects the final state, not the interim running row
    stored = store.get("job-1")
    assert stored is not None
    assert stored.state is JobState.PERSISTED


def test_failed_delivery_records_failed_with_error_code(tmp_path: Path) -> None:
    store = SqliteActivityStore(tmp_path / "activity.sqlite")

    result = execute_snapshot(
        bundle=_bundle(),
        context=_context(),
        delivery=_FailingDelivery(),
        activity=store,
        clock=_FrozenClock(),
    )

    assert result.state is JobState.FAILED
    assert result.error_code == "labarchives_write_failed"
    assert result.error_message == "LabArchives write failed."
    assert result.display_message == "LabArchives write failed."
    stored = store.get("job-1")
    assert stored is not None
    assert stored.state is JobState.FAILED


def test_errored_run_still_persists_with_error_outcome(tmp_path: Path) -> None:
    # C-QUEUE-05/C-SNAP-07: an errored run is still persisted, recording the
    # run outcome separately from the delivery state.
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    result = execute_snapshot(
        bundle=_bundle(),
        context=_context(
            source=SnapshotSource.TRIGGER_CELL, run_outcome=RunOutcome.ERROR
        ),
        delivery=FakeDelivery(),
        activity=store,
        clock=_FrozenClock(),
    )
    assert result.state is JobState.PERSISTED
    assert result.run_outcome is RunOutcome.ERROR


def test_persisted_record_carries_commit_clauses(tmp_path: Path) -> None:
    store = SqliteActivityStore(tmp_path / "activity.sqlite")
    result = execute_snapshot(
        bundle=_bundle(),
        context=_context(
            commit_hash=CommitHash("abcdef1234567890"),
            commit_status="created",
        ),
        delivery=FakeDelivery(),
        activity=store,
        clock=_FrozenClock(),
    )
    assert "Commit abcdef123456 created." in result.display_message

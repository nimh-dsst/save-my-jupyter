from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.container import build_services
from save_my_jupyter.domain.activity import ActivityRecord
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState, RunOutcome
from save_my_jupyter.domain.queue import Accepted
from save_my_jupyter.domain.requests import (
    NotebookContext,
    RequestedMetadata,
    SnapshotRequest,
)
from save_my_jupyter.domain.types import NotebookPath

if TYPE_CHECKING:
    import pytest


_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _request(tmp_path: Path) -> SnapshotRequest:
    return SnapshotRequest(
        source=SnapshotSource.MANUAL,
        notebook_context=NotebookContext(
            notebook_path=NotebookPath(str(tmp_path / "nb.ipynb")),
            notebook_name="nb.ipynb",
        ),
        metadata=RequestedMetadata(),
        notebook_content={"cells": [], "metadata": {}},
    )


def _activity_record(job_id: str) -> ActivityRecord:
    return ActivityRecord(
        job_id=job_id,
        submitted_at=_NOW,
        completed_at=_NOW,
        source=SnapshotSource.MANUAL,
        notebook_path="analysis/nb.ipynb",
        state=JobState.PERSISTED,
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
        display_message="Snapshot saved.",
    )


def test_activity_store_is_scoped_by_project_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    services_a = build_services(
        data_dir=data_dir,
        snapshots_dir=tmp_path / "snapshots-a",
        project_root=project_a,
        user_id="user-a",
        extension_version="0.1.0",
    )
    services_b = build_services(
        data_dir=data_dir,
        snapshots_dir=tmp_path / "snapshots-b",
        project_root=project_b,
        user_id="user-b",
        extension_version="0.1.0",
    )
    services_a_again = build_services(
        data_dir=data_dir,
        snapshots_dir=tmp_path / "snapshots-a2",
        project_root=project_a,
        user_id="user-a",
        extension_version="0.1.0",
    )
    try:
        services_a.activity.save(_activity_record("job-1"))

        assert services_a_again.activity.get("job-1") is not None
        assert services_b.activity.get("job-1") is None
        assert not (data_dir / "activity.sqlite").exists()
        assert len(list((data_dir / "projects").glob("*/activity.sqlite"))) == 2
    finally:
        services_a.worker_pool.shutdown()
        services_b.worker_pool.shutdown()
        services_a_again.worker_pool.shutdown()


def test_non_demo_pipeline_fails_when_session_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    services = build_services(
        data_dir=tmp_path / "data",
        snapshots_dir=tmp_path / "snapshots",
        user_id=f"missing-session-{tmp_path.name}",
        extension_version="0.1.0",
        demo_mode=False,
    )
    try:
        decision = services.coordinator.submit(
            job_id="job-1", request=_request(tmp_path)
        )
        services.worker_pool.join()
    finally:
        services.worker_pool.shutdown()

    assert isinstance(decision, Accepted)
    record = services.activity.get("job-1")
    assert record is not None
    assert record.state is JobState.FAILED
    assert record.error_code == "labarchives_session_expired"


def test_non_demo_pipeline_reports_missing_server_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCESS_KEYID", raising=False)
    monkeypatch.delenv("ACCESS_PWD", raising=False)
    services = build_services(
        data_dir=tmp_path / "data",
        snapshots_dir=tmp_path / "snapshots",
        user_id=f"missing-credentials-{tmp_path.name}",
        extension_version="0.1.0",
        demo_mode=False,
    )
    try:
        decision = services.coordinator.submit(
            job_id="job-1", request=_request(tmp_path)
        )
        services.worker_pool.join()
    finally:
        services.worker_pool.shutdown()

    assert isinstance(decision, Accepted)
    record = services.activity.get("job-1")
    assert record is not None
    assert record.state is JobState.FAILED
    assert record.error_code == "missing_labarchives_credentials"

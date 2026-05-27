from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.container import build_services
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import JobState
from save_my_jupyter.domain.queue import Accepted
from save_my_jupyter.domain.requests import (
    NotebookContext,
    RequestedMetadata,
    SnapshotRequest,
)
from save_my_jupyter.domain.types import NotebookPath

if TYPE_CHECKING:
    import pytest


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

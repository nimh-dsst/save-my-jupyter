from __future__ import annotations

from datetime import UTC, datetime

import pytest
from save_my_jupyter.api.parsers import parse_snapshot_request
from save_my_jupyter.domain import (
    ManualSnapshotRequest,
    TriggerCellSnapshotRequest,
    WatchedPathSnapshotRequest,
)
from save_my_jupyter.errors import SnapshotParseError


def test_parse_manual_snapshot_request() -> None:
    request = parse_snapshot_request(
        {
            "source": "manual",
            "commit_mode": "prompt",
            "client_timestamp": "2026-04-10T12:30:00Z",
            "notebook_context": {
                "notebook_path": "C:/repo/notebook.ipynb",
                "notebook_name": "notebook.ipynb",
                "document_id": "doc-1",
                "kernel_id": "kernel-1",
                "cell_ids": ["a", "b"],
            },
            "user_metadata": {
                "tags": ["baseline"],
                "notes": "note",
                "run_label": "run-1",
                "experiment_context": "ctx",
                "extra_fields": {"owner": "user"},
            },
        }
    )

    assert isinstance(request, ManualSnapshotRequest)
    assert request.notebook_context.notebook_name == "notebook.ipynb"
    assert request.user_metadata.tags == ("baseline",)
    assert request.client_timestamp == datetime(2026, 4, 10, 12, 30, tzinfo=UTC)


def test_parse_trigger_snapshot_requires_triggering_cell() -> None:
    with pytest.raises(SnapshotParseError, match="Trigger cell snapshots require"):
        parse_snapshot_request(
            {
                "source": "trigger_cell",
                "commit_mode": "always",
                "notebook_context": {
                    "notebook_path": "C:/repo/notebook.ipynb",
                    "notebook_name": "notebook.ipynb",
                },
            }
        )


def test_parse_trigger_snapshot_request() -> None:
    request = parse_snapshot_request(
        {
            "source": "trigger_cell",
            "commit_mode": "always",
            "notebook_context": {
                "notebook_path": "C:/repo/notebook.ipynb",
                "notebook_name": "notebook.ipynb",
                "triggering_cell_id": "cell-1",
            },
        }
    )

    assert isinstance(request, TriggerCellSnapshotRequest)
    assert str(request.notebook_context.triggering_cell_id) == "cell-1"


def test_parse_watched_path_snapshot_request() -> None:
    request = parse_snapshot_request(
        {
            "source": "watched_path",
            "commit_mode": "never",
            "notebook_context": {
                "notebook_path": "C:/repo/notebook.ipynb",
                "notebook_name": "notebook.ipynb",
            },
            "watched_path_event": {
                "relative_path": "outputs/result.csv",
                "event_type": "modified",
            },
        }
    )

    assert isinstance(request, WatchedPathSnapshotRequest)
    assert str(request.watched_path_event.relative_path) == "outputs/result.csv"

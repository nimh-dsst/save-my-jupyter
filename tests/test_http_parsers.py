from __future__ import annotations

from typing import Any

import pytest
from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.http.parsers import parse_snapshot_request


def _manual(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "manual",
        "notebook_context": {
            "notebook_path": "analysis/nb.ipynb",
            "notebook_name": "nb.ipynb",
        },
    }
    body.update(overrides)
    return body


def _code(raw: object) -> str:
    with pytest.raises(SnapshotError) as exc:
        parse_snapshot_request(raw)
    return exc.value.code


# --- body / source (C-FAIL-01) ---


def test_non_object_body_is_missing_json_body() -> None:
    assert _code(None) == "missing_json_body"
    assert _code("not-a-dict") == "missing_json_body"


def test_unknown_source_rejected() -> None:
    assert _code(_manual(source="watched_path")) == "invalid_snapshot_source"


def test_minimal_manual_request_parses() -> None:
    request = parse_snapshot_request(_manual())
    assert request.source is SnapshotSource.MANUAL
    assert request.notebook_context.notebook_path == "analysis/nb.ipynb"
    assert request.notebook_context.notebook_name == "nb.ipynb"
    assert request.commit_mode is None
    assert request.watched_paths == ()
    assert request.metadata.tags == ()


# --- trigger context (C-FAIL-01) ---


def test_trigger_without_triggering_cell_rejected() -> None:
    body = _manual(source="trigger_cell")
    assert _code(body) == "missing_triggering_cell"


def test_trigger_with_context_parses() -> None:
    body = _manual(source="trigger_cell")
    body["notebook_context"]["triggering_cell_id"] = "cell-1"
    body["notebook_context"]["triggered_cell_ids"] = ["cell-1", "cell-2"]
    body["notebook_context"]["cell_execution_count"] = 7
    request = parse_snapshot_request(body)
    assert request.source is SnapshotSource.TRIGGER_CELL
    assert request.notebook_context.triggering_cell_id == "cell-1"
    assert request.notebook_context.triggered_cell_ids == ("cell-1", "cell-2")
    assert request.notebook_context.cell_execution_count == 7


# --- commit mode ---


def test_commit_mode_parsed_and_validated() -> None:
    assert parse_snapshot_request(_manual(commit_mode="ask")).commit_mode is (
        CommitMode.ASK
    )
    assert _code(_manual(commit_mode="sometimes")) == "invalid_commit_mode"


# --- watched paths (C-WATCH-02 -> C-FAIL-01 codes) ---


def test_watched_paths_normalized() -> None:
    request = parse_snapshot_request(_manual(watched_paths=["outputs\\a.csv", "figs"]))
    assert request.watched_paths == ("outputs/a.csv", "figs")


def test_absolute_watched_path_rejected() -> None:
    assert _code(_manual(watched_paths=["/etc/passwd"])) == "absolute_path_not_allowed"


def test_traversing_watched_path_rejected() -> None:
    assert _code(_manual(watched_paths=["a/../b"])) == "path_escapes_root"


def test_watched_paths_must_be_a_list() -> None:
    assert _code(_manual(watched_paths="outputs")) == "invalid_sequence"


def test_watched_path_items_must_be_strings() -> None:
    assert _code(_manual(watched_paths=[1])) == "invalid_sequence_item"


# --- metadata + timestamp + content ---


def test_user_metadata_parsed() -> None:
    request = parse_snapshot_request(
        _manual(
            user_metadata={
                "tags": ["baseline", "gpu"],
                "run_label": "run-1",
                "notes": "a note",
            }
        )
    )
    assert request.metadata.tags == ("baseline", "gpu")
    assert request.metadata.run_label == "run-1"
    assert request.metadata.notes == "a note"


def test_client_timestamp_parsed_and_validated() -> None:
    request = parse_snapshot_request(
        _manual(client_timestamp="2026-05-26T12:00:00+00:00")
    )
    assert request.client_timestamp is not None
    assert _code(_manual(client_timestamp="not-a-date")) == "invalid_datetime"


def test_notebook_content_passed_through() -> None:
    request = parse_snapshot_request(_manual(notebook_content={"cells": []}))
    assert request.notebook_content == {"cells": []}

from __future__ import annotations

from collections.abc import Mapping

from save_my_jupyter.domain import (
    CellId,
    CommitMode,
    DocumentId,
    KernelId,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    RelativeWatchPath,
    SnapshotRequest,
    SnapshotSource,
    TriggerCellSnapshotRequest,
    UserMetadata,
    WatchedPathSnapshotRequest,
    WatchRegistrationRequest,
)
from save_my_jupyter.errors import SnapshotParseError
from save_my_jupyter.parsing import (
    normalize_relative_path_text,
    optional_mapping,
    optional_str,
    parse_datetime,
    require_mapping,
    require_str,
    str_tuple,
)
from save_my_jupyter.watchers.parsers import parse_watch_event


def parse_snapshot_request(raw: Mapping[str, object]) -> SnapshotRequest:
    source = SnapshotSource(require_str(raw.get("source"), field_name="source"))
    notebook_context = parse_notebook_context(
        require_mapping(raw.get("notebook_context"), field_name="notebook_context")
    )
    commit_mode = CommitMode(
        require_str(
            raw.get("commit_mode", CommitMode.PROMPT.value),
            field_name="commit_mode",
        )
    )
    user_metadata = parse_user_metadata(
        optional_mapping(raw.get("user_metadata"), field_name="user_metadata") or {}
    )
    client_timestamp = parse_datetime(
        raw.get("client_timestamp"),
        field_name="client_timestamp",
    )

    if source is SnapshotSource.MANUAL:
        return ManualSnapshotRequest(
            notebook_context=notebook_context,
            commit_mode=commit_mode,
            user_metadata=user_metadata,
            client_timestamp=client_timestamp,
        )

    if source is SnapshotSource.TRIGGER_CELL:
        if notebook_context.triggering_cell_id is None:
            raise SnapshotParseError(
                "Trigger cell snapshots require a triggering cell ID.",
                code="missing_triggering_cell",
            )
        return TriggerCellSnapshotRequest(
            notebook_context=notebook_context,
            commit_mode=commit_mode,
            user_metadata=user_metadata,
            client_timestamp=client_timestamp,
        )

    watched_path_event = parse_watch_event(
        require_mapping(raw.get("watched_path_event"), field_name="watched_path_event")
    )
    return WatchedPathSnapshotRequest(
        notebook_context=notebook_context,
        commit_mode=commit_mode,
        user_metadata=user_metadata,
        watched_path_event=watched_path_event,
        client_timestamp=client_timestamp,
    )


def parse_notebook_context(raw: Mapping[str, object]) -> NotebookContext:
    notebook_path = NotebookPath(
        require_str(raw.get("notebook_path"), field_name="notebook_path")
    )
    notebook_name = require_str(raw.get("notebook_name"), field_name="notebook_name")
    document_id = optional_str(raw.get("document_id"), field_name="document_id")
    kernel_id = optional_str(raw.get("kernel_id"), field_name="kernel_id")
    triggering_cell_id = optional_str(
        raw.get("triggering_cell_id"),
        field_name="triggering_cell_id",
    )

    return NotebookContext(
        notebook_path=notebook_path,
        notebook_name=notebook_name,
        document_id=DocumentId(document_id) if document_id is not None else None,
        kernel_id=KernelId(kernel_id) if kernel_id is not None else None,
        cell_ids=tuple(
            CellId(cell_id)
            for cell_id in str_tuple(raw.get("cell_ids"), field_name="cell_ids")
        ),
        triggering_cell_id=CellId(triggering_cell_id)
        if triggering_cell_id is not None
        else None,
    )


def parse_user_metadata(raw: Mapping[str, object]) -> UserMetadata:
    extra_fields = (
        optional_mapping(raw.get("extra_fields"), field_name="extra_fields") or {}
    )
    normalized_extra_fields: dict[str, str] = {}
    for key, value in extra_fields.items():
        normalized_extra_fields[str(key)] = require_str(
            value,
            field_name=f"extra_fields.{key}",
        )

    return UserMetadata(
        tags=str_tuple(raw.get("tags"), field_name="tags"),
        notes=optional_str(raw.get("notes"), field_name="notes"),
        run_label=optional_str(raw.get("run_label"), field_name="run_label"),
        experiment_context=optional_str(
            raw.get("experiment_context"),
            field_name="experiment_context",
        ),
        extra_fields=normalized_extra_fields,
    )


def parse_watch_registration_request(
    raw: Mapping[str, object],
) -> WatchRegistrationRequest:
    notebook_context = parse_notebook_context(
        require_mapping(raw.get("notebook_context"), field_name="notebook_context")
    )
    commit_mode = CommitMode(
        require_str(
            raw.get("commit_mode", CommitMode.PROMPT.value),
            field_name="commit_mode",
        )
    )
    user_metadata = parse_user_metadata(
        optional_mapping(raw.get("user_metadata"), field_name="user_metadata") or {}
    )
    watch_paths = tuple(
        RelativeWatchPath(normalize_relative_path_text(path))
        for path in str_tuple(raw.get("watch_paths"), field_name="watch_paths")
    )

    return WatchRegistrationRequest(
        notebook_context=notebook_context,
        commit_mode=commit_mode,
        user_metadata=user_metadata,
        watch_paths=watch_paths,
    )

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
    WatchRegistrationRequest,
)
from save_my_jupyter.errors import SnapshotParseError
from save_my_jupyter.parsing import (
    expect,
    maybe,
    normalize_path,
    parse_datetime,
    tuple_of,
)


def parse_snapshot_request(raw: Mapping[str, object]) -> SnapshotRequest:
    source = _source(raw.get("source"))
    notebook_context, commit_mode, user_metadata = _request_parts(raw)
    client_timestamp = parse_datetime(
        raw.get("client_timestamp"),
        field="client_timestamp",
    )

    if source is SnapshotSource.MANUAL:
        return ManualSnapshotRequest(
            notebook_context=notebook_context,
            commit_mode=commit_mode,
            user_metadata=user_metadata,
            client_timestamp=client_timestamp,
        )

    if source is SnapshotSource.TRIGGER_CELL:
        _require_triggering_cell(notebook_context)
        return TriggerCellSnapshotRequest(
            notebook_context=notebook_context,
            commit_mode=commit_mode,
            user_metadata=user_metadata,
            client_timestamp=client_timestamp,
        )

    raise SnapshotParseError(
        "Unsupported snapshot source.",
        code="invalid_snapshot_source",
        context={"field": "source"},
    )


def parse_notebook_context(raw: Mapping[str, object]) -> NotebookContext:
    document_id = maybe(raw.get("document_id"), str, field="document_id")
    kernel_id = maybe(raw.get("kernel_id"), str, field="kernel_id")
    triggering_cell_id = maybe(
        raw.get("triggering_cell_id"),
        str,
        field="triggering_cell_id",
    )
    cell_execution_count = maybe(
        raw.get("cell_execution_count"),
        int,
        field="cell_execution_count",
    )

    return NotebookContext(
        notebook_path=NotebookPath(
            expect(raw.get("notebook_path"), str, field="notebook_path")
        ),
        notebook_name=expect(raw.get("notebook_name"), str, field="notebook_name"),
        document_id=None if document_id is None else DocumentId(document_id),
        kernel_id=None if kernel_id is None else KernelId(kernel_id),
        cell_ids=tuple(
            CellId(cell_id)
            for cell_id in tuple_of(raw.get("cell_ids"), str, field="cell_ids")
        ),
        triggering_cell_id=None
        if triggering_cell_id is None
        else CellId(triggering_cell_id),
        cell_execution_count=cell_execution_count,
    )


def parse_user_metadata(raw: Mapping[str, object]) -> UserMetadata:
    extra_fields = maybe(raw.get("extra_fields"), Mapping, field="extra_fields") or {}
    parsed_extra_fields = {
        str(key): expect(value, str, field=f"extra_fields.{key}")
        for key, value in extra_fields.items()
    }
    tags = tuple_of(raw.get("tags"), str, field="tags")

    return UserMetadata(
        tags=_merge_tags(tags, _parse_tagme_field(parsed_extra_fields.get("tagme"))),
        notes=maybe(raw.get("notes"), str, field="notes"),
        run_label=maybe(raw.get("run_label"), str, field="run_label"),
        experiment_context=maybe(
            raw.get("experiment_context"),
            str,
            field="experiment_context",
        ),
        extra_fields=parsed_extra_fields,
    )


def parse_watch_registration_request(
    raw: Mapping[str, object],
) -> WatchRegistrationRequest:
    notebook_context, commit_mode, user_metadata = _request_parts(raw)

    return WatchRegistrationRequest(
        notebook_context=notebook_context,
        commit_mode=commit_mode,
        user_metadata=user_metadata,
        watch_paths=tuple(
            RelativeWatchPath(normalize_path(path))
            for path in tuple_of(raw.get("watch_paths"), str, field="watch_paths")
        ),
    )


def _request_parts(
    raw: Mapping[str, object],
) -> tuple[NotebookContext, CommitMode, UserMetadata]:
    return (
        parse_notebook_context(
            expect(raw.get("notebook_context"), Mapping, field="notebook_context")
        ),
        _commit_mode(
            raw.get("commit_mode", CommitMode.PROMPT.value),
            field="commit_mode",
        ),
        parse_user_metadata(
            maybe(raw.get("user_metadata"), Mapping, field="user_metadata") or {}
        ),
    )


def _commit_mode(value: object, *, field: str) -> CommitMode:
    raw_value = expect(value, str, field=field)
    try:
        return CommitMode(raw_value)
    except ValueError as exc:
        raise SnapshotParseError(
            f"Unsupported commit mode for {field}.",
            code="invalid_commit_mode",
            context={"field": field},
        ) from exc


def _source(value: object) -> SnapshotSource:
    raw_value = expect(value, str, field="source")
    try:
        return SnapshotSource(raw_value)
    except ValueError as exc:
        raise SnapshotParseError(
            "Unsupported snapshot source.",
            code="invalid_snapshot_source",
            context={"field": "source"},
        ) from exc


def _require_triggering_cell(notebook_context: NotebookContext) -> None:
    if notebook_context.triggering_cell_id is None:
        raise SnapshotParseError(
            "Trigger cell snapshots require a triggering cell ID.",
            code="missing_triggering_cell",
        )


def _parse_tagme_field(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    tags: list[str] = []
    for candidate in value.replace(";", ",").replace("\n", ",").split(","):
        tag = candidate.strip()
        if tag != "":
            tags.append(tag)
    return tuple(tags)


def _merge_tags(
    primary_tags: tuple[str, ...],
    extracted_tags: tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    for tag in [*primary_tags, *extracted_tags]:
        if tag not in merged:
            merged.append(tag)
    return tuple(merged)

"""Pure parsing of the snapshot-request JSON body into a domain request,
raising `SnapshotError` with the stable C-FAIL-01 codes. No Tornado here, so the
whole validation vocabulary is unit-tested directly (contracts C-API, C-FAIL)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import cast

from save_my_jupyter.application.snapshot.guards import validate_watched_path
from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.guards import WatchedPathRejected
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.requests import (
    NotebookContext,
    RequestedMetadata,
    SnapshotRequest,
)
from save_my_jupyter.domain.types import (
    CellId,
    DocumentId,
    KernelId,
    NotebookPath,
    RelativeWatchPath,
)

ACTIVITY_LIMIT_DEFAULT = 20
ACTIVITY_LIMIT_MIN = 1
ACTIVITY_LIMIT_MAX = 100


def parse_snapshot_request(raw: object) -> SnapshotRequest:
    body = _mapping(raw, code="missing_json_body", what="Request body")
    source = _source(body)
    return SnapshotRequest(
        source=source,
        notebook_context=_notebook_context(body, source),
        metadata=_metadata(body),
        commit_mode=_commit_mode(body),
        watched_paths=_watched_paths(body),
        run_outcome=_run_outcome(body),
        client_timestamp=_timestamp(body),
        notebook_content=_notebook_content(body),
    )


def _source(body: Mapping[str, object]) -> SnapshotSource:
    value = body.get("source")
    if isinstance(value, str):
        try:
            return SnapshotSource(value)
        except ValueError:
            pass
    raise SnapshotError(
        f"Unknown snapshot source: {value!r}.", code="invalid_snapshot_source"
    )


def _notebook_context(
    body: Mapping[str, object], source: SnapshotSource
) -> NotebookContext:
    raw = _mapping(
        body.get("notebook_context"),
        code="invalid_notebook_context",
        what="notebook_context",
    )
    triggering = _optional_str(
        raw, "triggering_cell_id", code="invalid_notebook_context"
    )
    if source is SnapshotSource.TRIGGER_CELL and triggering is None:
        raise SnapshotError(
            "Trigger snapshots require a triggering cell.",
            code="missing_triggering_cell",
        )
    document = _optional_str(raw, "document_id", code="invalid_notebook_context")
    kernel = _optional_str(raw, "kernel_id", code="invalid_notebook_context")
    return NotebookContext(
        notebook_path=NotebookPath(_notebook_path(raw)),
        notebook_name=_require_str(raw, "notebook_name", code="invalid_notebook_name"),
        document_id=DocumentId(document) if document is not None else None,
        kernel_id=KernelId(kernel) if kernel is not None else None,
        triggering_cell_id=CellId(triggering) if triggering is not None else None,
        triggered_cell_ids=tuple(
            CellId(value) for value in _str_list(raw, "triggered_cell_ids")
        ),
        cell_execution_count=_optional_int(
            raw, "cell_execution_count", code="invalid_notebook_context"
        ),
    )


def _metadata(body: Mapping[str, object]) -> RequestedMetadata:
    raw = body.get("user_metadata")
    if raw is None:
        return RequestedMetadata()
    meta = _mapping(raw, code="invalid_user_metadata", what="user_metadata")
    return RequestedMetadata(
        tags=tuple(_str_list(meta, "tags")),
        run_label=_optional_str(meta, "run_label", code="invalid_user_metadata"),
        notes=_optional_str(meta, "notes", code="invalid_user_metadata"),
        extra_fields=_str_map(meta, "extra_fields"),
    )


def _commit_mode(body: Mapping[str, object]) -> CommitMode | None:
    value = body.get("commit_mode")
    if value is None:
        return None
    if isinstance(value, str):
        if value == "prompt":
            return CommitMode.ASK
        try:
            return CommitMode(value)
        except ValueError:
            pass
    raise SnapshotError(f"Unknown commit mode: {value!r}.", code="invalid_commit_mode")


def _run_outcome(body: Mapping[str, object]) -> RunOutcome | None:
    value = body.get("run_outcome")
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return RunOutcome(value)
        except ValueError:
            pass
    raise SnapshotError(f"Unknown run outcome: {value!r}.", code="invalid_run_outcome")


def _watched_paths(
    body: Mapping[str, object],
) -> tuple[RelativeWatchPath, ...] | None:
    value = body.get("watched_paths")
    if value is None:
        return None
    if not isinstance(value, list):
        raise SnapshotError("watched_paths must be a list.", code="invalid_sequence")
    result: list[RelativeWatchPath] = []
    for item in value:
        if not isinstance(item, str):
            raise SnapshotError(
                "watched_paths items must be strings.", code="invalid_sequence_item"
            )
        validation = validate_watched_path(item)
        if isinstance(validation, WatchedPathRejected):
            raise SnapshotError(
                validation.message, code=validation.code, context={"path": item}
            )
        result.append(RelativeWatchPath(validation.normalized))
    return tuple(result)


def _timestamp(body: Mapping[str, object]) -> datetime | None:
    value = body.get("client_timestamp")
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise SnapshotError(
        "client_timestamp must be an ISO-8601 datetime.", code="invalid_datetime"
    )


def _notebook_content(body: Mapping[str, object]) -> Mapping[str, object] | None:
    value = body.get("notebook_content")
    if value is None:
        return None
    return _mapping(value, code="invalid_notebook_content", what="notebook_content")


def _mapping(value: object, *, code: str, what: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast("Mapping[str, object]", value)
    raise SnapshotError(f"{what} must be a JSON object.", code=code)


def _notebook_path(body: Mapping[str, object]) -> str:
    value = _require_str(body, "notebook_path", code="invalid_notebook_path")
    normalized = value.strip().replace("\\", "/")
    if (
        normalized == ""
        or normalized.startswith("/")
        or _has_windows_drive_prefix(normalized)
    ):
        raise SnapshotError(
            "notebook_path must be a relative .ipynb path.",
            code="invalid_notebook_path",
            context={"path": value},
        )
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise SnapshotError(
            "notebook_path must stay within the Jupyter server root.",
            code="invalid_notebook_path",
            context={"path": value},
        )
    normalized = "/".join(parts)
    if PurePosixPath(normalized).suffix.lower() != ".ipynb":
        raise SnapshotError(
            "notebook_path must point to an .ipynb file.",
            code="invalid_notebook_path",
            context={"path": value},
        )
    return normalized


def _has_windows_drive_prefix(path: str) -> bool:
    return len(path) >= 2 and path[0].isalpha() and path[1] == ":"


def _require_str(body: Mapping[str, object], key: str, *, code: str) -> str:
    value = body.get(key)
    if isinstance(value, str):
        return value
    raise SnapshotError(f"{key} must be a string.", code=code)


def _optional_str(body: Mapping[str, object], key: str, *, code: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise SnapshotError(f"{key} must be a string.", code=code)


def _optional_int(body: Mapping[str, object], key: str, *, code: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError(f"{key} must be an integer.", code=code)
    return value


def _str_list(body: Mapping[str, object], key: str) -> list[str]:
    value = body.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SnapshotError(f"{key} must be a list.", code="invalid_sequence")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SnapshotError(
                f"{key} items must be strings.", code="invalid_sequence_item"
            )
        items.append(item)
    return items


def _str_map(body: Mapping[str, object], key: str) -> dict[str, str]:
    value = body.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SnapshotError(f"{key} must be an object.", code="invalid_user_metadata")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            raise SnapshotError(
                f"{key} keys and values must be strings.",
                code="invalid_user_metadata",
            )
        result[raw_key] = raw_value
    return result


def parse_activity_limit(raw: str) -> int:
    try:
        limit = int(raw)
    except ValueError as exc:
        raise SnapshotError("limit must be an integer.", code="invalid_limit") from exc
    if not ACTIVITY_LIMIT_MIN <= limit <= ACTIVITY_LIMIT_MAX:
        raise SnapshotError(
            f"limit must be between {ACTIVITY_LIMIT_MIN} and {ACTIVITY_LIMIT_MAX}.",
            code="invalid_limit",
            context={"limit": raw},
        )
    return limit

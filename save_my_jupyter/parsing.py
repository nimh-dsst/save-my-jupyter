from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .errors import PathNormalizationError, SnapshotParseError

_TYPE_NAMES: dict[object, str] = {
    Mapping: "mapping",
    bool: "boolean",
    str: "string",
}


def _type_name(expected_type: object) -> str:
    return _TYPE_NAMES.get(expected_type, getattr(expected_type, "__name__", "value"))


def expect[T](
    value: object,
    expected_type: type[T],
    *,
    field: str,
    kind: str | None = None,
    code: str | None = None,
) -> T:
    if isinstance(value, expected_type):
        return value

    resolved_kind = kind or _type_name(expected_type)
    raise SnapshotParseError(
        f"Expected {resolved_kind} for {field}.",
        code=code or f"invalid_{resolved_kind.replace(' ', '_')}",
        context={"field": field},
    )


def maybe[T](
    value: object,
    expected_type: type[T],
    *,
    field: str,
    kind: str | None = None,
    code: str | None = None,
) -> T | None:
    return (
        None
        if value is None
        else expect(value, expected_type, field=field, kind=kind, code=code)
    )


def tuple_of[T](
    value: object,
    item_type: type[T],
    *,
    field: str,
    item_kind: str | None = None,
) -> tuple[T, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        resolved_item_kind = item_kind or _type_name(item_type)
        raise SnapshotParseError(
            f"Expected sequence of {resolved_item_kind} values for {field}.",
            code="invalid_sequence",
            context={"field": field},
        )

    resolved_item_kind = item_kind or _type_name(item_type)
    result: list[T] = []
    for index, item in enumerate(value):
        if not isinstance(item, item_type):
            raise SnapshotParseError(
                f"Expected {resolved_item_kind} item for {field}.",
                code="invalid_sequence_item",
                context={"field": f"{field}[{index}]"},
            )
        result.append(item)
    return tuple(result)


def parse_datetime(value: object | None = None, *, field: str) -> datetime:
    if value is None:
        return datetime.now(UTC)

    raw = expect(value, str, field=field)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotParseError(
            f"Expected ISO 8601 datetime for {field}.",
            code="invalid_datetime",
            context={"field": field},
        ) from exc


def normalize_path(path: str) -> str:
    candidate = PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute():
        raise PathNormalizationError(
            "Absolute paths are not allowed.",
            code="absolute_path_not_allowed",
            context={"path": path},
        )

    normalized = candidate.as_posix()
    if normalized in {".", ""}:
        return "."

    if any(part == ".." for part in candidate.parts):
        raise PathNormalizationError(
            "Path cannot escape the configured root.",
            code="path_escapes_root",
            context={"path": path},
        )

    return normalized


def resolve_path(path: str) -> Path:
    return Path(path).expanduser().resolve()

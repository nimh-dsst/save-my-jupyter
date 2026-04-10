from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast

from .errors import PathNormalizationError, SnapshotParseError


def require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast("Mapping[str, object]", value)

    raise SnapshotParseError(
        f"Expected mapping for {field_name}.",
        code="invalid_mapping",
        context={"field": field_name},
    )


def require_str(value: object, *, field_name: str) -> str:
    if isinstance(value, str):
        return value

    raise SnapshotParseError(
        f"Expected string for {field_name}.",
        code="invalid_string",
        context={"field": field_name},
    )


def optional_str(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return require_str(value, field_name=field_name)


def require_bool(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value

    raise SnapshotParseError(
        f"Expected boolean for {field_name}.",
        code="invalid_boolean",
        context={"field": field_name},
    )


def optional_mapping(value: object, *, field_name: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    return require_mapping(value, field_name=field_name)


def str_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise SnapshotParseError(
            f"Expected sequence of strings for {field_name}.",
            code="invalid_sequence",
            context={"field": field_name},
        )

    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise SnapshotParseError(
                f"Expected string item for {field_name}.",
                code="invalid_sequence_item",
                context={"field": f"{field_name}[{index}]"},
            )
        result.append(item)
    return tuple(result)


def parse_datetime(value: object, *, field_name: str) -> datetime:
    if value is None:
        return datetime.now(UTC)
    raw = require_str(value, field_name=field_name)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def normalize_relative_path_text(value: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute():
        raise PathNormalizationError(
            "Absolute paths are not allowed.",
            code="absolute_path_not_allowed",
            context={"path": value},
        )

    normalized = candidate.as_posix()
    if normalized in {".", ""}:
        return "."

    if any(part == ".." for part in candidate.parts):
        raise PathNormalizationError(
            "Path cannot escape the configured root.",
            code="path_escapes_root",
            context={"path": value},
        )

    return normalized


def resolve_existing_or_new_path(value: str) -> Path:
    return Path(value).expanduser().resolve()

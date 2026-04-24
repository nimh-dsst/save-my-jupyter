from __future__ import annotations

from datetime import UTC, datetime

import pytest
from save_my_jupyter.errors import PathNormalizationError, SnapshotParseError
from save_my_jupyter.parsing import (
    expect,
    maybe,
    normalize_path,
    parse_datetime,
    tuple_of,
)


def test_expect_rejects_invalid_type() -> None:
    with pytest.raises(SnapshotParseError) as exc_info:
        expect(1, str, field="name")

    assert exc_info.value.code == "invalid_string"
    assert exc_info.value.context == {"field": "name"}


def test_maybe_returns_none_for_none() -> None:
    assert maybe(None, str, field="name") is None


def test_tuple_of_returns_empty_tuple_for_none() -> None:
    assert tuple_of(None, str, field="tags") == ()


def test_tuple_of_rejects_non_string_items() -> None:
    with pytest.raises(SnapshotParseError) as exc_info:
        tuple_of(["ok", 2], str, field="tags")

    assert exc_info.value.code == "invalid_sequence_item"
    assert exc_info.value.context == {"field": "tags[1]"}


def test_parse_datetime_defaults_to_current_utc_time() -> None:
    before = datetime.now(UTC)
    parsed = parse_datetime(field="client_timestamp")
    after = datetime.now(UTC)

    assert before <= parsed <= after


def test_parse_datetime_rejects_invalid_iso_strings() -> None:
    with pytest.raises(SnapshotParseError) as exc_info:
        parse_datetime("not-a-timestamp", field="client_timestamp")

    assert exc_info.value.code == "invalid_datetime"
    assert exc_info.value.context == {"field": "client_timestamp"}


def test_normalize_path_rejects_absolute_paths() -> None:
    with pytest.raises(PathNormalizationError) as exc_info:
        normalize_path("/tmp/output.csv")

    assert exc_info.value.code == "absolute_path_not_allowed"
    assert exc_info.value.context == {"path": "/tmp/output.csv"}

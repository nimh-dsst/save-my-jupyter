from __future__ import annotations

from collections.abc import Mapping

from save_my_jupyter.domain import PathEventType, RelativeWatchPath, WatchedPathEvent
from save_my_jupyter.parsing import (
    normalize_relative_path_text,
    parse_datetime,
    require_str,
)


def parse_watch_event(raw: Mapping[str, object]) -> WatchedPathEvent:
    return WatchedPathEvent(
        relative_path=RelativeWatchPath(
            normalize_relative_path_text(
                require_str(raw.get("relative_path"), field_name="relative_path")
            )
        ),
        event_type=PathEventType(
            require_str(raw.get("event_type"), field_name="event_type")
        ),
        timestamp=parse_datetime(raw.get("timestamp"), field_name="timestamp"),
    )

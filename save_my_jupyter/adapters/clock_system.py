"""System `Clock` adapter: real wall-clock time as timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

"""System `Clock` adapter: real wall-clock time as timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

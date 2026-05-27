from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time, injected so snapshot timestamps are testable.

    Implementations must return a timezone-aware UTC `datetime`.
    """

    def now(self) -> datetime: ...

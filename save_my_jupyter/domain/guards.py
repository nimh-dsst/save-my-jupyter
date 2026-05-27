from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchedPathAccepted:
    """A watched-path entry that passed validation, in normalized POSIX form."""

    normalized: str


@dataclass(frozen=True, slots=True)
class WatchedPathRejected:
    """A rejected watched-path entry with the exact user-facing message
    (contract C-WATCH-02) and a stable error code (C-FAIL-01) the HTTP boundary
    can surface without re-deriving the reason."""

    message: str
    code: str


type WatchedPathValidation = WatchedPathAccepted | WatchedPathRejected

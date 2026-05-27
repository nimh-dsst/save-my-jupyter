from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchedPathAccepted:
    """A watched-path entry that passed validation, in normalized POSIX form."""

    normalized: str


@dataclass(frozen=True, slots=True)
class WatchedPathRejected:
    """A rejected watched-path entry with the exact user-facing message
    (contract C-WATCH-02)."""

    message: str


type WatchedPathValidation = WatchedPathAccepted | WatchedPathRejected

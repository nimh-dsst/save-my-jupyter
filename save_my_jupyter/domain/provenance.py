from __future__ import annotations

from enum import Enum


class ConfigLayer(str, Enum):
    """Which configuration layer supplied a resolved value, highest precedence
    first (contract C-CONFIG-01). Carried as per-field provenance so the panel
    can label `(inferred)` values inline (contract C-CONFIG-11)."""

    def __str__(self) -> str:
        return self.value

    REQUEST = "request"
    NOTEBOOK = "notebook"
    USER = "user"
    REPO = "repo"
    INFERRED = "inferred"
    FALLBACK = "fallback"

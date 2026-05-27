from __future__ import annotations

from collections.abc import Mapping


class SnapshotError(Exception):
    """Base error for the rewritten pipeline. Carries a stable namespaced `code`
    (contract C-FAIL-01) and a structured `context` for the HTTP error envelope
    (contract C-API-02). The `message` is human-facing."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        context: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context: dict[str, str] = dict(context or {})

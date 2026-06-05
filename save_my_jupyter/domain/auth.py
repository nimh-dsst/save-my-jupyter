from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthStartResult:
    status: str
    message: str
    auth_url: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthStatusResult:
    status: str
    pending_request_id: str | None = None
    user_email: str | None = None
    stored_user_email: str | None = None
    stored_notebook_names: tuple[str, ...] = ()

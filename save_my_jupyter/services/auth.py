from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.labarchives import load_labapi


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


@dataclass(frozen=True, slots=True)
class LabArchivesSession:
    user_email: str
    user: Any
    client: Any


@dataclass(slots=True)
class PendingAuthRequest:
    callback_url: str
    client: Any
    created_at: datetime
    request_id: str
    user_id: str


class AuthServiceImpl:
    def __init__(self) -> None:
        self._pending_requests: dict[str, PendingAuthRequest] = {}
        self._sessions: dict[str, LabArchivesSession] = {}

    def start_auth(self, user_id: str, callback_base_url: str) -> AuthStartResult:
        request_id = uuid4().hex
        callback_url = f"{callback_base_url.rstrip('/')}/{request_id}"
        labapi = load_labapi()
        try:
            client = labapi.Client()
            auth_url = client.generate_auth_url(callback_url)
        except labapi.AuthenticationError as exc:
            raise LabArchivesWriteError(
                (
                    "LabArchives credentials are not configured for the Jupyter "
                    "server. Set ACCESS_KEYID and ACCESS_PWD in the server "
                    "environment before connecting."
                ),
                code="missing_labarchives_credentials",
                context={"callback_url": callback_url},
            ) from exc
        self._pending_requests[request_id] = PendingAuthRequest(
            callback_url=callback_url,
            client=client,
            created_at=datetime.now(UTC),
            request_id=request_id,
            user_id=user_id,
        )
        return AuthStartResult(
            status="pending",
            message="Open the LabArchives authentication page to continue.",
            auth_url=auth_url,
            request_id=request_id,
        )

    def get_authenticated_user(self, user_id: str) -> LabArchivesSession:
        session = self._sessions.get(user_id)
        if session is None:
            raise LabArchivesWriteError(
                "No LabArchives session is available for this user.",
                code="missing_labarchives_session",
                context={"user_id": user_id},
            )
        return session

    def complete_auth(
        self,
        request_id: str,
        *,
        email: str,
        auth_code: str,
    ) -> LabArchivesSession:
        pending_request = self._pending_requests.pop(request_id, None)
        if pending_request is None:
            raise LabArchivesWriteError(
                "Authentication request was not found or has expired.",
                code="missing_auth_request",
                context={"request_id": request_id},
            )

        user = pending_request.client.login(email, auth_code)
        existing_session = self._sessions.get(pending_request.user_id)
        if existing_session is not None:
            existing_session.client.close()

        session = LabArchivesSession(
            user_email=user.email,
            user=user,
            client=pending_request.client,
        )
        self._sessions[pending_request.user_id] = session
        return session

    def fail_pending_auth(self, request_id: str) -> None:
        pending_request = self._pending_requests.pop(request_id, None)
        if pending_request is None:
            return
        pending_request.client.close()

    def get_auth_status(self, user_id: str) -> AuthStatusResult:
        session = self._sessions.get(user_id)
        if session is not None:
            return AuthStatusResult(
                status="authenticated",
                user_email=session.user_email,
            )

        for pending_request in self._pending_requests.values():
            if pending_request.user_id == user_id:
                return AuthStatusResult(
                    status="pending",
                    pending_request_id=pending_request.request_id,
                )

        return AuthStatusResult(status="unauthenticated")

    def set_authenticated_user(self, user_id: str, session: LabArchivesSession) -> None:
        existing_session = self._sessions.get(user_id)
        if existing_session is not None:
            existing_session.client.close()
        self._sessions[user_id] = session

    def clear_session(self, user_id: str) -> None:
        session = self._sessions.pop(user_id, None)
        if session is not None:
            session.client.close()

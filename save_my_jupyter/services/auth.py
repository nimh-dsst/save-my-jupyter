from __future__ import annotations

import importlib
import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import uuid4

from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.labarchives import load_labapi

_DEFAULT_API_URL = "https://api.labarchives.com"
_KEYRING_SERVICE_PREFIX = "save-my-jupyter.labarchives.profile"


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


@dataclass(frozen=True, slots=True)
class StoredLabArchivesNotebook:
    notebook_id: str
    notebook_name: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class StoredLabArchivesProfile:
    api_url: str
    labarchives_user_id: str
    notebooks: tuple[StoredLabArchivesNotebook, ...]
    saved_at: str
    user_email: str
    user_id: str


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class _NotebookLike(Protocol):
    id: str
    name: str
    is_default: bool


class _NotebookCollectionLike(Protocol):
    def all_values(self) -> list[_NotebookLike]: ...


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


class _KeyringProfileStore:
    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend if backend is not None else _load_keyring_backend()

    def load(self, *, api_url: str, user_id: str) -> StoredLabArchivesProfile | None:
        backend = self._backend
        if backend is None:
            return None

        try:
            raw_value = backend.get_password(
                _keyring_service_name(api_url),
                user_id,
            )
        except Exception:
            return None

        if raw_value is None:
            return None
        return _parse_stored_profile(raw_value)

    def save(
        self,
        *,
        api_url: str,
        user_id: str,
        profile: StoredLabArchivesProfile,
    ) -> None:
        backend = self._backend
        if backend is None:
            return

        try:
            backend.set_password(
                _keyring_service_name(api_url),
                user_id,
                json.dumps(asdict(profile), sort_keys=True),
            )
        except Exception:
            return


class AuthServiceImpl:
    def __init__(self, *, keyring_backend: KeyringBackend | None = None) -> None:
        self._pending_requests: dict[str, PendingAuthRequest] = {}
        self._sessions: dict[str, LabArchivesSession] = {}
        self._profile_store = _KeyringProfileStore(keyring_backend)

    def start_auth(self, user_id: str, callback_base_url: str) -> AuthStartResult:
        request_id = uuid4().hex
        callback_url = f"{callback_base_url.rstrip('/')}/{request_id}"
        labapi = load_labapi()
        stored_profile = self.get_stored_profile(user_id)
        client: Any | None = None
        try:
            client = labapi.Client()
            auth_url = client.generate_auth_url(callback_url)
        except Exception as exc:
            if client is not None:
                with suppress(Exception):
                    client.close()
            raise _translate_auth_exception(
                exc,
                phase="start_auth",
                callback_url=callback_url,
            ) from exc

        message = "Open the LabArchives authentication page to continue."
        if stored_profile is not None:
            message = (
                "Open the LabArchives authentication page to continue. "
                f"Previously connected as {stored_profile.user_email}."
            )
        self._pending_requests[request_id] = PendingAuthRequest(
            callback_url=callback_url,
            client=client,
            created_at=datetime.now(UTC),
            request_id=request_id,
            user_id=user_id,
        )
        return AuthStartResult(
            status="pending",
            message=message,
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

        try:
            user = pending_request.client.login(email, auth_code)
        except Exception as exc:
            with suppress(Exception):
                pending_request.client.close()
            raise _translate_auth_exception(
                exc,
                phase="complete_auth",
                callback_url=pending_request.callback_url,
                request_id=request_id,
                user_email=email,
            ) from exc
        existing_session = self._sessions.get(pending_request.user_id)
        if existing_session is not None:
            existing_session.client.close()

        session = LabArchivesSession(
            user_email=user.email,
            user=user,
            client=pending_request.client,
        )
        self._sessions[pending_request.user_id] = session
        self._persist_profile(pending_request.user_id, pending_request.client, user)
        return session

    def fail_pending_auth(self, request_id: str) -> None:
        pending_request = self._pending_requests.pop(request_id, None)
        if pending_request is None:
            return
        pending_request.client.close()

    def get_auth_status(self, user_id: str) -> AuthStatusResult:
        stored_profile = self.get_stored_profile(user_id)

        session = self._sessions.get(user_id)
        if session is not None:
            return AuthStatusResult(
                status="authenticated",
                user_email=session.user_email,
                stored_user_email=(
                    stored_profile.user_email if stored_profile is not None else None
                ),
                stored_notebook_names=_stored_notebook_names(stored_profile),
            )

        for pending_request in self._pending_requests.values():
            if pending_request.user_id == user_id:
                return AuthStatusResult(
                    status="pending",
                    pending_request_id=pending_request.request_id,
                    stored_user_email=(
                        stored_profile.user_email
                        if stored_profile is not None
                        else None
                    ),
                    stored_notebook_names=_stored_notebook_names(stored_profile),
                )

        if stored_profile is not None:
            return AuthStatusResult(
                status="unauthenticated",
                stored_user_email=stored_profile.user_email,
                stored_notebook_names=_stored_notebook_names(stored_profile),
            )

        return AuthStatusResult(status="unauthenticated")

    def set_authenticated_user(self, user_id: str, session: LabArchivesSession) -> None:
        existing_session = self._sessions.get(user_id)
        if existing_session is not None:
            existing_session.client.close()
        self._sessions[user_id] = session
        self._persist_profile(user_id, session.client, session.user)

    def clear_session(self, user_id: str) -> None:
        session = self._sessions.pop(user_id, None)
        if session is not None:
            session.client.close()

    def get_stored_profile(self, user_id: str) -> StoredLabArchivesProfile | None:
        return self._profile_store.load(api_url=_current_api_url(), user_id=user_id)

    def _persist_profile(self, user_id: str, client: Any, user: Any) -> None:
        profile = StoredLabArchivesProfile(
            api_url=_client_base_url(client),
            labarchives_user_id=str(getattr(user, "id", "")),
            notebooks=_iter_notebook_infos(user),
            saved_at=datetime.now(UTC).isoformat(),
            user_email=str(getattr(user, "email", "")),
            user_id=user_id,
        )
        self._profile_store.save(
            api_url=profile.api_url,
            user_id=user_id,
            profile=profile,
        )


def _current_api_url() -> str:
    return os.getenv("API_URL", _DEFAULT_API_URL).strip() or _DEFAULT_API_URL


def _client_base_url(client: Any) -> str:
    base_url = getattr(client, "_base_url", None)
    if isinstance(base_url, str) and base_url.strip():
        return base_url
    return _current_api_url()


def _stored_notebook_names(
    profile: StoredLabArchivesProfile | None,
) -> tuple[str, ...]:
    if profile is None:
        return ()
    return tuple(notebook.notebook_name for notebook in profile.notebooks)


def _keyring_service_name(api_url: str) -> str:
    return f"{_KEYRING_SERVICE_PREFIX}:{api_url}"


def _load_keyring_backend() -> KeyringBackend | None:
    try:
        keyring = importlib.import_module("keyring")
    except ImportError:
        return None
    return cast(KeyringBackend, keyring)


def _translate_auth_exception(
    exc: Exception,
    *,
    phase: str,
    callback_url: str,
    request_id: str | None = None,
    user_email: str | None = None,
) -> LabArchivesWriteError:
    message = str(exc)
    lowered = message.lower()
    context = _auth_error_context(
        callback_url=callback_url,
        request_id=request_id,
        user_email=user_email,
    )

    if "access_keyid" in lowered or "access_pwd" in lowered:
        return LabArchivesWriteError(
            (
                "LabArchives credentials are not configured for the Jupyter "
                "server. Set ACCESS_KEYID and ACCESS_PWD in the server "
                "environment before connecting."
            ),
            code="missing_labarchives_credentials",
            context=context,
        )

    if (
        "tls ca certificate bundle" in lowered
        or "tls cacert bundle" in lowered
        or "ca cert bundle" in lowered
        or "cacert.pem" in lowered
    ):
        return LabArchivesWriteError(
            (
                "The Jupyter server TLS CA bundle is not configured correctly for "
                "LabArchives. Check REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE, "
                "SSL_CERT_FILE, or the Python certifi installation in the server "
                "environment."
            ),
            code="invalid_tls_ca_bundle",
            context=context,
        )

    if "certificate verify failed" in lowered or exc.__class__.__name__ == "SSLError":
        return LabArchivesWriteError(
            (
                "TLS verification failed while connecting to LabArchives. Check "
                "the server CA trust configuration or the LabArchives "
                "certificate chain."
            ),
            code="labarchives_tls_verification_failed",
            context=context,
        )

    if phase == "complete_auth":
        return LabArchivesWriteError(
            "LabArchives authentication could not be completed.",
            code="labarchives_authentication_failed",
            context=context,
        )

    return LabArchivesWriteError(
        "Unable to start the LabArchives authentication flow.",
        code="labarchives_auth_start_failed",
        context=context,
    )


def _auth_error_context(
    *,
    callback_url: str,
    request_id: str | None,
    user_email: str | None,
) -> dict[str, str]:
    context = {
        "api_url": _current_api_url(),
        "callback_url": callback_url,
        "curl_ca_bundle": os.getenv("CURL_CA_BUNDLE", ""),
        "requests_ca_bundle": os.getenv("REQUESTS_CA_BUNDLE", ""),
        "ssl_cert_file": os.getenv("SSL_CERT_FILE", ""),
    }
    if request_id is not None:
        context["request_id"] = request_id
    if user_email is not None:
        context["user_email"] = user_email
    return context


def _iter_notebook_infos(user: Any) -> tuple[StoredLabArchivesNotebook, ...]:
    notebooks = cast(
        _NotebookCollectionLike | None,
        getattr(user, "notebooks", None),
    )
    if notebooks is None:
        return ()

    result: list[StoredLabArchivesNotebook] = []
    for notebook in notebooks.all_values():
        notebook_id = notebook.id.strip()
        notebook_name = notebook.name.strip()
        if notebook_id == "" or notebook_name == "":
            continue
        result.append(
            StoredLabArchivesNotebook(
                notebook_id=notebook_id,
                notebook_name=notebook_name,
                is_default=notebook.is_default,
            )
        )
    return tuple(result)


def _parse_stored_profile(raw_value: str) -> StoredLabArchivesProfile | None:
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    api_url = payload.get("api_url")
    labarchives_user_id = payload.get("labarchives_user_id")
    notebooks = payload.get("notebooks")
    saved_at = payload.get("saved_at")
    user_email = payload.get("user_email")
    user_id = payload.get("user_id")

    if not all(
        isinstance(value, str)
        for value in (api_url, labarchives_user_id, saved_at, user_email, user_id)
    ):
        return None

    if not isinstance(notebooks, list):
        return None

    parsed_notebooks: list[StoredLabArchivesNotebook] = []
    for notebook in notebooks:
        if not isinstance(notebook, dict):
            return None
        notebook_id = notebook.get("notebook_id")
        notebook_name = notebook.get("notebook_name")
        is_default = notebook.get("is_default")
        if not isinstance(notebook_id, str) or not isinstance(notebook_name, str):
            return None
        if not isinstance(is_default, bool):
            return None
        parsed_notebooks.append(
            StoredLabArchivesNotebook(
                notebook_id=notebook_id,
                notebook_name=notebook_name,
                is_default=is_default,
            )
        )

    return StoredLabArchivesProfile(
        api_url=api_url,
        labarchives_user_id=labarchives_user_id,
        notebooks=tuple(parsed_notebooks),
        saved_at=saved_at,
        user_email=user_email,
        user_id=user_id,
    )

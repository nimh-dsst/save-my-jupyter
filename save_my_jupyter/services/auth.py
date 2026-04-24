from __future__ import annotations

import importlib
import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol, cast
from uuid import uuid4

import labapi

from save_my_jupyter.errors import LabArchivesWriteError

_API_URL_ENV_VAR = "API_URL"
_CURL_CA_BUNDLE_ENV_VAR = "CURL_CA_BUNDLE"
_DEFAULT_API_URL = "https://api.labarchives.com"
_KEYRING_SERVICE_PREFIX = "save-my-jupyter.labarchives.profile"
_REQUESTS_CA_BUNDLE_ENV_VAR = "REQUESTS_CA_BUNDLE"
_SSL_CERT_FILE_ENV_VAR = "SSL_CERT_FILE"
_PROMPT_MESSAGE = "Open the LabArchives authentication page to continue."
_START_FAILURE_CODE = "labarchives_auth_start_failed"
_START_FAILURE_MESSAGE = "Unable to start the LabArchives authentication flow."
_COMPLETE_FAILURE_CODE = "labarchives_authentication_failed"
_COMPLETE_FAILURE_MESSAGE = "LabArchives authentication could not be completed."
_MISSING_CREDENTIALS_CODE = "missing_labarchives_credentials"
_MISSING_CREDENTIALS_MESSAGE = (
    "LabArchives credentials are not configured for the Jupyter server. "
    "Set ACCESS_KEYID and ACCESS_PWD in the server environment before connecting."
)
_INVALID_TLS_CA_BUNDLE_CODE = "invalid_tls_ca_bundle"
_INVALID_TLS_CA_BUNDLE_MESSAGE = (
    "The Jupyter server TLS CA bundle is not configured correctly for "
    "LabArchives. Check REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE, SSL_CERT_FILE, "
    "or the Python certifi installation in the server environment."
)
_TLS_VERIFICATION_FAILED_CODE = "labarchives_tls_verification_failed"
_TLS_VERIFICATION_FAILED_MESSAGE = (
    "TLS verification failed while connecting to LabArchives. Check "
    "the server CA trust configuration or the LabArchives certificate chain."
)
_CREDENTIAL_ERROR_MARKERS = ("access_keyid", "access_pwd")
_TLS_CA_BUNDLE_ERROR_MARKERS = (
    "tls ca certificate bundle",
    "tls cacert bundle",
    "ca cert bundle",
    "cacert.pem",
)


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
class StoredNotebook:
    notebook_id: str
    notebook_name: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class StoredProfile:
    api_url: str
    labarchives_user_id: str
    notebooks: tuple[StoredNotebook, ...]
    saved_at: str
    user_email: str
    user_id: str

    @property
    def notebook_names(self) -> tuple[str, ...]:
        return tuple(notebook.notebook_name for notebook in self.notebooks)

    @classmethod
    def from_user(
        cls,
        *,
        user_id: str,
        api_url: str,
        client: Any,
        user: Any,
    ) -> StoredProfile:
        client_api_url = getattr(client, "_base_url", None)
        if not isinstance(client_api_url, str) or not client_api_url.strip():
            client_api_url = api_url

        notebooks = cast(
            _NotebookCollectionLike | None,
            getattr(user, "notebooks", None),
        )
        stored_notebooks: tuple[StoredNotebook, ...] = ()
        if notebooks is not None:
            parsed_notebooks: list[StoredNotebook] = []
            for notebook in notebooks.all_values():
                notebook_id = notebook.id.strip()
                notebook_name = notebook.name.strip()
                if notebook_id == "" or notebook_name == "":
                    continue
                parsed_notebooks.append(
                    StoredNotebook(
                        notebook_id=notebook_id,
                        notebook_name=notebook_name,
                        is_default=notebook.is_default,
                    )
                )
            stored_notebooks = tuple(parsed_notebooks)

        return cls(
            api_url=client_api_url,
            labarchives_user_id=str(getattr(user, "id", "")),
            notebooks=stored_notebooks,
            saved_at=datetime.now(UTC).isoformat(),
            user_email=str(getattr(user, "email", "")),
            user_id=user_id,
        )

    def to_keyring_value(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_keyring_value(cls, raw_value: str) -> StoredProfile | None:
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

        parsed_notebooks: list[StoredNotebook] = []
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
                StoredNotebook(
                    notebook_id=notebook_id,
                    notebook_name=notebook_name,
                    is_default=is_default,
                )
            )

        return cls(
            api_url=api_url,
            labarchives_user_id=labarchives_user_id,
            notebooks=tuple(parsed_notebooks),
            saved_at=saved_at,
            user_email=user_email,
            user_id=user_id,
        )


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...


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
class PendingAuth:
    callback_url: str
    client: Any
    request_id: str
    user_id: str


class _ProfileStore:
    def __init__(self, *, api_url: str, backend: KeyringBackend | None = None) -> None:
        self._keyring_backend = backend
        self._service_name = f"{_KEYRING_SERVICE_PREFIX}:{api_url}"
        if self._keyring_backend is not None:
            return

        try:
            self._keyring_backend = cast(
                KeyringBackend,
                importlib.import_module("keyring"),
            )
        except ImportError:
            self._keyring_backend = None

    def load(self, *, user_id: str) -> StoredProfile | None:
        keyring_backend = self._keyring_backend
        if keyring_backend is None:
            return None

        try:
            raw_value = keyring_backend.get_password(self._service_name, user_id)
        except Exception:
            return None

        if raw_value is None:
            return None
        return StoredProfile.from_keyring_value(raw_value)

    def save(
        self,
        *,
        user_id: str,
        profile: StoredProfile,
    ) -> None:
        keyring_backend = self._keyring_backend
        if keyring_backend is None:
            return

        try:
            keyring_backend.set_password(
                self._service_name,
                user_id,
                profile.to_keyring_value(),
            )
        except Exception:
            return


class AuthServiceImpl:
    def __init__(self, *, keyring_backend: KeyringBackend | None = None) -> None:
        self._api_url = os.getenv(_API_URL_ENV_VAR, _DEFAULT_API_URL).strip()
        if self._api_url == "":
            self._api_url = _DEFAULT_API_URL

        self._pending_requests: dict[str, PendingAuth] = {}
        self._sessions: dict[str, LabArchivesSession] = {}
        self._profile_store = _ProfileStore(
            api_url=self._api_url,
            backend=keyring_backend,
        )

    def start_auth(self, user_id: str, callback_base_url: str) -> AuthStartResult:
        request_id = uuid4().hex
        callback_url = f"{callback_base_url.rstrip('/')}/{request_id}"
        stored_profile = self.get_stored_profile(user_id)
        client: Any | None = None
        try:
            client = labapi.Client(base_url=self._api_url)
            auth_url = client.generate_auth_url(callback_url)
        except Exception as exc:
            if client is not None:
                with suppress(Exception):
                    client.close()
            _raise_auth_error(
                exc,
                api_url=self._api_url,
                fallback_code=_START_FAILURE_CODE,
                fallback_message=_START_FAILURE_MESSAGE,
                callback_url=callback_url,
            )

        message = _PROMPT_MESSAGE
        if stored_profile is not None:
            message = (
                f"{_PROMPT_MESSAGE} Previously connected as "
                f"{stored_profile.user_email}."
            )
        self._pending_requests[request_id] = PendingAuth(
            callback_url=callback_url,
            client=client,
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
        pending_auth = self._pending_requests.pop(request_id, None)
        if pending_auth is None:
            raise LabArchivesWriteError(
                "Authentication request was not found or has expired.",
                code="missing_auth_request",
                context={"request_id": request_id},
            )

        try:
            user = pending_auth.client.login(email, auth_code)
        except Exception as exc:
            with suppress(Exception):
                pending_auth.client.close()
            _raise_auth_error(
                exc,
                api_url=self._api_url,
                fallback_code=_COMPLETE_FAILURE_CODE,
                fallback_message=_COMPLETE_FAILURE_MESSAGE,
                callback_url=pending_auth.callback_url,
                request_id=request_id,
                user_email=email,
            )
        existing_session = self._sessions.get(pending_auth.user_id)
        if existing_session is not None:
            existing_session.client.close()

        session = LabArchivesSession(
            user_email=user.email,
            user=user,
            client=pending_auth.client,
        )
        self._sessions[pending_auth.user_id] = session
        self._persist_profile(pending_auth.user_id, pending_auth.client, user)
        return session

    def fail_pending_auth(self, request_id: str) -> None:
        pending_auth = self._pending_requests.pop(request_id, None)
        if pending_auth is None:
            return
        pending_auth.client.close()

    def get_auth_status(self, user_id: str) -> AuthStatusResult:
        stored_profile = self.get_stored_profile(user_id)
        stored_user_email = (
            stored_profile.user_email if stored_profile is not None else None
        )
        stored_notebook_names = (
            stored_profile.notebook_names if stored_profile is not None else ()
        )

        session = self._sessions.get(user_id)
        if session is not None:
            return AuthStatusResult(
                status="authenticated",
                user_email=session.user_email,
                stored_user_email=stored_user_email,
                stored_notebook_names=stored_notebook_names,
            )

        pending_request_id = next(
            (
                pending_auth.request_id
                for pending_auth in self._pending_requests.values()
                if pending_auth.user_id == user_id
            ),
            None,
        )
        if pending_request_id is not None:
            return AuthStatusResult(
                status="pending",
                pending_request_id=pending_request_id,
                stored_user_email=stored_user_email,
                stored_notebook_names=stored_notebook_names,
            )

        return AuthStatusResult(
            status="unauthenticated",
            stored_user_email=stored_user_email,
            stored_notebook_names=stored_notebook_names,
        )

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

    def get_stored_profile(self, user_id: str) -> StoredProfile | None:
        return self._profile_store.load(user_id=user_id)

    def _persist_profile(self, user_id: str, client: Any, user: Any) -> None:
        profile = StoredProfile.from_user(
            user_id=user_id,
            api_url=self._api_url,
            client=client,
            user=user,
        )
        self._profile_store.save(
            user_id=user_id,
            profile=profile,
        )


def _raise_auth_error(
    exc: Exception,
    *,
    api_url: str,
    fallback_code: str,
    fallback_message: str,
    callback_url: str,
    request_id: str | None = None,
    user_email: str | None = None,
) -> NoReturn:
    error_text = str(exc)
    lowered_error_text = error_text.lower()
    context = {
        "api_url": api_url,
        "callback_url": callback_url,
        "curl_ca_bundle": os.getenv(_CURL_CA_BUNDLE_ENV_VAR, ""),
        "requests_ca_bundle": os.getenv(_REQUESTS_CA_BUNDLE_ENV_VAR, ""),
        "ssl_cert_file": os.getenv(_SSL_CERT_FILE_ENV_VAR, ""),
    }
    if request_id is not None:
        context["request_id"] = request_id
    if user_email is not None:
        context["user_email"] = user_email

    labapi_authentication_error = getattr(labapi, "AuthenticationError", None)
    if (
        isinstance(labapi_authentication_error, type)
        and isinstance(exc, labapi_authentication_error)
        and any(marker in lowered_error_text for marker in _CREDENTIAL_ERROR_MARKERS)
    ):
        raise LabArchivesWriteError(
            _MISSING_CREDENTIALS_MESSAGE,
            code=_MISSING_CREDENTIALS_CODE,
            context=context,
        ) from exc

    if any(marker in lowered_error_text for marker in _TLS_CA_BUNDLE_ERROR_MARKERS):
        raise LabArchivesWriteError(
            _INVALID_TLS_CA_BUNDLE_MESSAGE,
            code=_INVALID_TLS_CA_BUNDLE_CODE,
            context=context,
        ) from exc

    if (
        "certificate verify failed" in lowered_error_text
        or exc.__class__.__name__ == "SSLError"
    ):
        raise LabArchivesWriteError(
            _TLS_VERIFICATION_FAILED_MESSAGE,
            code=_TLS_VERIFICATION_FAILED_CODE,
            context=context,
        ) from exc

    raise LabArchivesWriteError(
        fallback_message,
        code=fallback_code,
        context=context,
    ) from exc

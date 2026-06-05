from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

import pytest
from save_my_jupyter.adapters.labarchives import auth as auth_module
from save_my_jupyter.adapters.labarchives.auth import AuthServiceImpl, StoredProfile
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.env import load_server_dotenv

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


class _MovableClock:
    def __init__(self) -> None:
        self._now = _NOW

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class _FakeAuthClient:
    def __init__(self, *, base_url: str, strict_cert: bool = True) -> None:
        self.base_url = base_url
        self.strict_cert = strict_cert
        self.closed = False

    def generate_auth_url(self, callback_url: str) -> str:
        return f"https://auth.test/login?callback={callback_url}"

    def login(self, email: str, auth_code: str) -> Any:
        del auth_code
        return type(
            "User",
            (),
            {"email": email, "id": "la-user-1", "notebooks": None},
        )()

    def close(self) -> None:
        self.closed = True


class _MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_delete = False

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        if self.fail_delete:
            raise RuntimeError("delete failed")
        del self.values[(service_name, username)]


def _install_labapi_restore_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> list[_FakeAuthClient]:
    clients: list[_FakeAuthClient] = []

    class _RestoredUser:
        def __init__(
            self,
            labarchives_user_id: str,
            email: str,
            notebooks: list[Any],
            client: _FakeAuthClient,
        ) -> None:
            self.id = labarchives_user_id
            self.email = email
            self.notebooks = notebooks
            self.client = client

    class _NotebookInit:
        def __init__(
            self, notebook_id: str, notebook_name: str, is_default: bool
        ) -> None:
            self.id = notebook_id
            self.name = notebook_name
            self.is_default = is_default

    user_module = ModuleType("labapi.user")
    user_module.__dict__["User"] = _RestoredUser
    util_module = ModuleType("labapi.util")
    util_module.__dict__["NotebookInit"] = _NotebookInit
    monkeypatch.setitem(sys.modules, "labapi.user", user_module)
    monkeypatch.setitem(sys.modules, "labapi.util", util_module)
    monkeypatch.setattr(
        auth_module.labapi,
        "Client",
        lambda *, base_url, strict_cert=True: _record_client(
            clients, base_url=base_url, strict_cert=strict_cert
        ),
    )
    return clients


def _record_client(
    clients: list[_FakeAuthClient], *, base_url: str, strict_cert: bool = True
) -> _FakeAuthClient:
    client = _FakeAuthClient(base_url=base_url, strict_cert=strict_cert)
    clients.append(client)
    return client


def _profile(user_id: str) -> str:
    return json.dumps(
        {
            "api_url": "https://api.labarchives.com",
            "labarchives_user_id": "la-user-1",
            "notebooks": [],
            "saved_at": _NOW.isoformat(),
            "user_email": "user@example.com",
            "user_id": user_id,
        }
    )


def test_start_auth_without_server_credentials_fails_with_admin_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACCESS_KEYID", raising=False)
    monkeypatch.delenv("ACCESS_PWD", raising=False)
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring())

    with pytest.raises(SnapshotError) as exc:
        service.start_auth("user-1", "https://jupyter.test/callback")

    assert exc.value.code == "missing_labarchives_credentials"
    assert "Set ACCESS_KEYID and ACCESS_PWD" in str(exc.value)


def test_start_auth_reads_credentials_from_dotenv(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCESS_KEYID", raising=False)
    monkeypatch.delenv("ACCESS_PWD", raising=False)
    (tmp_path / ".env").write_text(
        "ACCESS_KEYID=dotenv-key\nACCESS_PWD=dotenv-secret\n",
        encoding="utf-8",
    )
    clients: list[_FakeAuthClient] = []
    monkeypatch.setattr(
        auth_module.labapi,
        "Client",
        lambda *, base_url, strict_cert=True: _record_client(
            clients, base_url=base_url, strict_cert=strict_cert
        ),
    )
    load_server_dotenv(tmp_path)
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring())

    service.start_auth("user-1", "https://jupyter.test/callback")

    assert clients


def test_start_auth_passes_labapi_strict_cert_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    monkeypatch.delenv("SMJ_STRICT_CERT", raising=False)
    clients: list[_FakeAuthClient] = []
    monkeypatch.setattr(
        auth_module.labapi,
        "Client",
        lambda *, base_url, strict_cert=True: _record_client(
            clients, base_url=base_url, strict_cert=strict_cert
        ),
    )
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring())

    service.start_auth("user-1", "https://jupyter.test/callback")

    assert clients[0].strict_cert is True


def test_start_auth_can_disable_labapi_strict_cert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    monkeypatch.setenv("SMJ_STRICT_CERT", "false")
    clients: list[_FakeAuthClient] = []
    monkeypatch.setattr(
        auth_module.labapi,
        "Client",
        lambda *, base_url, strict_cert=True: _record_client(
            clients, base_url=base_url, strict_cert=strict_cert
        ),
    )
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring())

    service.start_auth("user-1", "https://jupyter.test/callback")

    assert clients[0].strict_cert is False


def test_pending_auth_expires_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    clients: list[_FakeAuthClient] = []

    def client_factory(*, base_url: str, strict_cert: bool = True) -> _FakeAuthClient:
        client = _FakeAuthClient(base_url=base_url, strict_cert=strict_cert)
        clients.append(client)
        return client

    monkeypatch.setattr(auth_module.labapi, "Client", client_factory)
    clock = _MovableClock()
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring(), clock=clock.now)

    result = service.start_auth("user-1", "https://jupyter.test/callback")
    assert result.request_id is not None

    clock.advance(timedelta(seconds=61))
    status = service.get_auth_status("user-1")

    assert status.status == "unauthenticated"
    assert clients[0].closed is True
    with pytest.raises(SnapshotError) as exc:
        service.complete_auth(
            result.request_id, email="user@example.com", auth_code="code"
        )
    assert exc.value.code == "missing_auth_request"


def test_logout_invalidates_pending_auth_for_user_and_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    monkeypatch.setattr(
        auth_module.labapi,
        "Client",
        lambda *, base_url, strict_cert=True: _FakeAuthClient(
            base_url=base_url, strict_cert=strict_cert
        ),
    )
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring())

    result = service.start_auth("legacy-user", "https://jupyter.test/callback")
    assert result.request_id is not None

    service.logout("current-user", user_id_aliases=("legacy-user",))

    with pytest.raises(SnapshotError) as exc:
        service.complete_auth(
            result.request_id, email="user@example.com", auth_code="code"
        )
    assert exc.value.code == "missing_auth_request"


def test_unknown_failed_callback_is_reported_as_missing_request() -> None:
    service = AuthServiceImpl(keyring_backend=_MemoryKeyring())

    with pytest.raises(SnapshotError) as exc:
        service.fail_pending_auth("missing-request")

    assert exc.value.code == "missing_auth_request"


def test_logout_surfaces_keyring_delete_failure() -> None:
    keyring = _MemoryKeyring()
    service = AuthServiceImpl(keyring_backend=keyring)
    service_name = "save-my-jupyter.labarchives.profile:https://api.labarchives.com"
    keyring.values[(service_name, "user-1")] = _profile("user-1")
    keyring.fail_delete = True

    with pytest.raises(SnapshotError) as exc:
        service.logout("user-1")

    assert exc.value.code == "labarchives_logout_failed"


def test_stored_profile_alias_is_restored_and_migrated() -> None:
    keyring = _MemoryKeyring()
    service = AuthServiceImpl(keyring_backend=keyring)
    service_name = "save-my-jupyter.labarchives.profile:https://api.labarchives.com"
    keyring.values[(service_name, "anonymous")] = _profile("anonymous")

    profile = service.get_stored_profile("current-user", user_id_aliases=("anonymous",))

    assert isinstance(profile, StoredProfile)
    assert profile.user_email == "user@example.com"


def test_expired_session_does_not_immediately_restore_stored_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    _install_labapi_restore_fakes(monkeypatch)
    keyring = _MemoryKeyring()
    service_name = "save-my-jupyter.labarchives.profile:https://api.labarchives.com"
    keyring.values[(service_name, "user-1")] = _profile("user-1")
    service = AuthServiceImpl(keyring_backend=keyring)

    restored = service.get_auth_status("user-1")
    assert restored.status == "authenticated"

    service.clear_session("user-1")
    status = service.get_auth_status("user-1")

    assert status.status == "unauthenticated"
    assert status.stored_user_email == "user@example.com"


def test_stored_profile_restore_can_disable_labapi_strict_cert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_KEYID", "key")
    monkeypatch.setenv("ACCESS_PWD", "secret")
    monkeypatch.setenv("SMJ_STRICT_CERT", "off")
    clients = _install_labapi_restore_fakes(monkeypatch)
    keyring = _MemoryKeyring()
    service_name = "save-my-jupyter.labarchives.profile:https://api.labarchives.com"
    keyring.values[(service_name, "user-1")] = _profile("user-1")
    service = AuthServiceImpl(keyring_backend=keyring)

    status = service.get_auth_status("user-1")

    assert status.status == "authenticated"
    assert clients[0].strict_cert is False

from __future__ import annotations

from save_my_jupyter.application.auth.keyring_migration import (
    delete_profile,
    load_profile,
)

_SERVICE = "save-my-jupyter"
_CURRENT = "user-current"
_ALIASES = ("user-legacy-1", "user-legacy-2")


class _MemoryKeyring:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


def test_load_returns_current_profile_when_present() -> None:
    keyring = _MemoryKeyring()
    keyring.set_password(_SERVICE, _CURRENT, "tokens")
    value = load_profile(
        keyring, service=_SERVICE, current_username=_CURRENT, alias_usernames=_ALIASES
    )
    assert value == "tokens"


def test_load_falls_back_to_alias_and_rewrites_under_current() -> None:
    keyring = _MemoryKeyring()
    keyring.set_password(_SERVICE, "user-legacy-2", "legacy-tokens")
    value = load_profile(
        keyring, service=_SERVICE, current_username=_CURRENT, alias_usernames=_ALIASES
    )
    assert value == "legacy-tokens"
    # rewritten under the current key so the next read no longer needs the alias
    assert keyring.get_password(_SERVICE, _CURRENT) == "legacy-tokens"


def test_load_prefers_current_over_alias() -> None:
    keyring = _MemoryKeyring()
    keyring.set_password(_SERVICE, _CURRENT, "current")
    keyring.set_password(_SERVICE, "user-legacy-1", "legacy")
    value = load_profile(
        keyring, service=_SERVICE, current_username=_CURRENT, alias_usernames=_ALIASES
    )
    assert value == "current"


def test_load_returns_none_when_no_profile_anywhere() -> None:
    keyring = _MemoryKeyring()
    value = load_profile(
        keyring, service=_SERVICE, current_username=_CURRENT, alias_usernames=_ALIASES
    )
    assert value is None


def test_delete_removes_current_and_all_aliases() -> None:
    keyring = _MemoryKeyring()
    keyring.set_password(_SERVICE, _CURRENT, "a")
    keyring.set_password(_SERVICE, "user-legacy-1", "b")
    keyring.set_password(_SERVICE, "user-legacy-2", "c")
    delete_profile(
        keyring, service=_SERVICE, current_username=_CURRENT, alias_usernames=_ALIASES
    )
    assert keyring.get_password(_SERVICE, _CURRENT) is None
    assert keyring.get_password(_SERVICE, "user-legacy-1") is None
    assert keyring.get_password(_SERVICE, "user-legacy-2") is None

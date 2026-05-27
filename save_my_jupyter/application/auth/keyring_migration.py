"""Keyring profile read/delete with legacy-alias migration (target CONFIGURE/
auth, contracts C-AUTH-08, C-AUTH-04). Pure policy over the KeyringStore port:
the OS credential library is never imported here."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from save_my_jupyter.ports import KeyringStore


def load_profile(
    keyring: KeyringStore,
    *,
    service: str,
    current_username: str,
    alias_usernames: Sequence[str],
) -> str | None:
    """Read the stored profile, preferring the current user id and falling back
    to legacy aliases. A legacy hit is rewritten under the current id so future
    reads no longer depend on the alias (contract C-AUTH-08)."""
    current = keyring.get_password(service, current_username)
    if current is not None:
        return current
    for alias in alias_usernames:
        legacy = keyring.get_password(service, alias)
        if legacy is not None:
            keyring.set_password(service, current_username, legacy)
            return legacy
    return None


def delete_profile(
    keyring: KeyringStore,
    *,
    service: str,
    current_username: str,
    alias_usernames: Sequence[str],
) -> None:
    """Remove the current profile and every legacy alias (contract C-AUTH-04)."""
    keyring.delete_password(service, current_username)
    for alias in alias_usernames:
        keyring.delete_password(service, alias)

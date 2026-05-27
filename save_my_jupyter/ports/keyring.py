from __future__ import annotations

from typing import Protocol


class KeyringStore(Protocol):
    """OS credential-store seam for persisting the LabArchives profile.

    The pure layers depend on this Protocol; only the adapter imports the
    `keyring` library (contract C-AUTH-02).
    """

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...

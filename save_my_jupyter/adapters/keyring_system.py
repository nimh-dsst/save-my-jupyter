"""System `KeyringStore` adapter over the OS credential store. The only place
the `keyring` library is imported; the LabArchives profile lives here, never in
the notebook, repo, or working tree (contract C-AUTH-02)."""

from __future__ import annotations

import keyring


class SystemKeyring:
    def get_password(self, service: str, username: str) -> str | None:
        return keyring.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        keyring.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        keyring.delete_password(service, username)

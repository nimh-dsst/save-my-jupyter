"""LabArchives auth service.

GATE-UNVERIFIABLE: the labapi sign-in calls need a real LabArchives account, so
the OAuth start/complete path is not exercised by the test suite and is marked
below. Profile persistence is delegated to the verified keyring-migration policy
(load/delete with legacy aliases, contracts C-AUTH-02/04/08). The snapshot path
gates on ``is_authenticated`` so an unconfigured server cleanly rejects
(C-QUEUE-03) rather than half-working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from save_my_jupyter.application.auth.keyring_migration import (
    delete_profile,
    load_profile,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from save_my_jupyter.ports import KeyringStore

_KEYRING_SERVICE = "save-my-jupyter"


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthStatus:
    authenticated: bool
    user_email: str | None
    stored_user_email: str | None
    pending_request_id: str | None
    stored_notebook_names: tuple[str, ...]


class AuthService:
    def __init__(
        self,
        keyring: KeyringStore,
        *,
        user_id: str,
        user_id_aliases: Sequence[str] = (),
    ) -> None:
        self._keyring = keyring
        self._user_id = user_id
        self._aliases = tuple(user_id_aliases)
        self._session: Any | None = None
        self._user_email: str | None = None

    def is_authenticated(self) -> bool:
        return self._session is not None

    def current_session(self) -> Any | None:
        return self._session

    def user_email(self) -> str:
        return self._user_email or ""

    def status(self) -> AuthStatus:
        stored = load_profile(
            self._keyring,
            service=_KEYRING_SERVICE,
            current_username=self._user_id,
            alias_usernames=self._aliases,
        )
        return AuthStatus(
            authenticated=self.is_authenticated(),
            user_email=self._user_email,
            stored_user_email=self._user_email if stored is not None else None,
            pending_request_id=None,
            stored_notebook_names=(),
        )

    def logout(self) -> None:
        self._session = None
        self._user_email = None
        delete_profile(
            self._keyring,
            service=_KEYRING_SERVICE,
            current_username=self._user_id,
            alias_usernames=self._aliases,
        )

    def adopt_session(self, *, session: Any, user_email: str) -> None:
        """Wire a labapi session after a completed sign-in. The OAuth start/
        complete flow that produces ``session`` is the gate-unverifiable part and
        is finished during a real-LabArchives smoke test."""
        self._session = session
        self._user_email = user_email

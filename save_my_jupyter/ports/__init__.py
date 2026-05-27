"""Protocol seams for IO. Imports only `save_my_jupyter.domain` and the stdlib.

Concrete implementations live in `save_my_jupyter.adapters`. The pure layers
(`domain`, `application`) depend on these Protocols, never on the libraries that
implement them — enforced by `tests/test_architecture.py`.
"""

from __future__ import annotations

from save_my_jupyter.ports.activity import ActivityStore
from save_my_jupyter.ports.clock import Clock
from save_my_jupyter.ports.delivery import Delivery
from save_my_jupyter.ports.filesystem import FileSystem
from save_my_jupyter.ports.keyring import KeyringStore

__all__ = [
    "ActivityStore",
    "Clock",
    "Delivery",
    "FileSystem",
    "KeyringStore",
]

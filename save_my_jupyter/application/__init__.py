"""Framework-free use-case layer. Pure policy/build functions plus orchestrators
that perform IO only through `save_my_jupyter.ports` Protocols. Must not import
Tornado, dulwich, labapi, sqlite3, keyring, or requests (enforced by
`tests/test_architecture.py`)."""

from __future__ import annotations

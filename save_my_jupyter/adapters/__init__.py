"""Concrete IO adapters implementing the `save_my_jupyter.ports` Protocols.

Import the specific adapter module you need; this package root stays empty so
adapters can pull in heavy IO libraries (dulwich, labapi, sqlite3, keyring)
without that cost leaking into callers that only need one of them.
"""

from __future__ import annotations

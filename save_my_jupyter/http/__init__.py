"""HTTP boundary: thin async Tornado handlers plus the pure request parsing and
response serialization they delegate to. `parsers.py` and `responses.py` import
no Tornado, so the JSON contract (C-API, C-FAIL) is unit-tested directly."""

from __future__ import annotations

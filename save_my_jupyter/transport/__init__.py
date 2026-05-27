"""Transport boundary (HTTP/JSON over Tornado): thin async handlers plus the
pure request parsing and response serialization they delegate to. Handlers do
only parse -> call an application use-case -> serialize; no business logic lives
here. `parsers.py` and `responses.py` import no Tornado, so the JSON contract
(C-API, C-FAIL) is unit-tested directly."""

from __future__ import annotations

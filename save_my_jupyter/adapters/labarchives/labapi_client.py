"""labapi binding for the LabArchivesClient seam.

GATE-UNVERIFIABLE: this is the only module that calls the real ``labapi``
library, which needs a live LabArchives account, so it is not exercised by the
test suite. The call patterns (``session.user.notebooks[name]``, ``.dir(seg)``
navigation, ``.create(Type, name, if_exists=...)``, ``page.entries.create(...)``,
``labapi.Attachment(stream, mime, name, description)``, ``.id`` / ``.delete()``)
are ported faithfully from the previous implementation; the delivery
orchestration in ``delivery.py`` is what's unit-tested (against a fake client).
A real-LabArchives smoke test is required before trusting this path.
"""

from __future__ import annotations

from contextlib import suppress
from io import BytesIO
from typing import Any

import labapi

_URL_ATTRIBUTE_NAMES = ("url", "web_url", "html_url", "permalink")
_URL_METHOD_NAMES = ("url", "web_url", "html_url", "permalink", "get_url")


class LabApiClient:
    def __init__(self, session: Any) -> None:
        self._session = session
        self._directories: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}

    def create_directory(
        self, *, notebook_name: str, root_path: str, directory_name: str
    ) -> str:
        directory = self._session.user.notebooks[notebook_name]
        for segment in (part for part in root_path.split("/") if part):
            directory = directory.dir(segment)
        snapshot = directory.create(
            labapi.NotebookDirectory,
            directory_name,
            if_exists=labapi.InsertBehavior.Raise,
        )
        self._directories[str(snapshot.id)] = snapshot
        return str(snapshot.id)

    def create_page(self, *, directory_id: str, page_name: str) -> str:
        page = self._directories[directory_id].create(
            labapi.NotebookPage, page_name, if_exists=labapi.InsertBehavior.Raise
        )
        self._pages[str(page.id)] = page
        return str(page.id)

    def write_page_html(self, *, page_id: str, html: str) -> None:
        self._pages[page_id].entries.create(labapi.TextEntry, html)

    def attach_file(
        self,
        *,
        page_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        description: str | None = None,
    ) -> None:
        attachment = labapi.Attachment(
            BytesIO(content), mime_type, filename, description or filename
        )
        self._pages[page_id].entries.create(labapi.AttachmentEntry, attachment)

    def delete_directory(self, *, directory_id: str) -> None:
        self._directories[directory_id].delete()

    def directory_url(self, *, directory_id: str) -> str | None:
        directory = self._directories.get(directory_id)
        if directory is None:
            return None
        return _object_url(directory)


def _object_url(value: Any) -> str | None:
    for attribute_name in _URL_ATTRIBUTE_NAMES:
        candidate = getattr(value, attribute_name, None)
        if isinstance(candidate, str) and _is_http_url(candidate):
            return candidate
    for method_name in _URL_METHOD_NAMES:
        method = getattr(value, method_name, None)
        if not callable(method):
            continue
        with suppress(Exception):
            candidate = method()
            if isinstance(candidate, str) and _is_http_url(candidate):
                return candidate
    return None


def _is_http_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))

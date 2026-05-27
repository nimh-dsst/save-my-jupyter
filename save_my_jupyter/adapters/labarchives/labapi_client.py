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

from io import BytesIO
from typing import Any

import labapi


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
        self, *, page_id: str, filename: str, mime_type: str, content: bytes
    ) -> None:
        attachment = labapi.Attachment(BytesIO(content), mime_type, filename, filename)
        self._pages[page_id].entries.create(labapi.AttachmentEntry, attachment)

    def delete_directory(self, *, directory_id: str) -> None:
        self._directories[directory_id].delete()

    def directory_url(self, *, directory_id: str) -> str | None:
        # The labapi web URL for a directory is not part of the ported call set;
        # the receipt degrades to the metadata page name until wired (C-DEST-05).
        del directory_id
        return None

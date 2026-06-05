"""The minimal LabArchives operations the delivery orchestration needs, behind a
Protocol so the orchestration (directory -> metadata page -> artifact pages ->
atomic cleanup) is testable with a fake. Only the concrete `LabApiClient`
binding (labapi_client.py) touches the labapi library."""

from __future__ import annotations

from typing import Protocol


class LabArchivesClient(Protocol):
    def create_directory(
        self, *, notebook_name: str, root_path: str, directory_name: str
    ) -> str:
        """Create the snapshot directory under the rendered root path and return
        an opaque directory id."""
        ...

    def create_page(self, *, directory_id: str, page_name: str) -> str:
        """Create a page in the directory and return its id."""
        ...

    def ensure_directory_path(
        self, *, parent_directory_id: str, relative_path: str
    ) -> str:
        """Create or reuse child directories below a parent and return the final id."""
        ...

    def write_page_html(self, *, page_id: str, html: str) -> None: ...

    def attach_file(
        self,
        *,
        page_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        description: str | None = None,
    ) -> None: ...

    def delete_directory(self, *, directory_id: str) -> None:
        """Best-effort move of the directory to API Deleted Items (cleanup)."""
        ...

    def directory_url(self, *, directory_id: str) -> str | None: ...

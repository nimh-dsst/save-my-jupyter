"""LabArchives delivery orchestration (target DELIVER, contracts C-DEST-01..05).
Creates one directory, the canonical 00 Metadata page, then a page per artifact;
on any failure it best-effort moves the directory to API Deleted Items and
raises. Pure orchestration over the LabArchivesClient seam, so it is tested with
a fake; the labapi binding is the only unverifiable part."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.labarchives.metadata import render_metadata_page
from save_my_jupyter.domain.delivery import DeliveryReceipt
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.types import RemoteUrl

if TYPE_CHECKING:
    from save_my_jupyter.adapters.labarchives.client import LabArchivesClient
    from save_my_jupyter.domain.delivery import SnapshotBundle

_METADATA_PAGE_NAME = "00 Metadata"


class LabArchivesDelivery:
    def __init__(self, client: LabArchivesClient) -> None:
        self._client = client

    def deliver(self, bundle: SnapshotBundle) -> DeliveryReceipt:
        metadata_html = render_metadata_page(
            bundle.metadata,
            artifact_page_names=[artifact.page_name for artifact in bundle.artifacts],
        )
        directory_id = self._client.create_directory(
            notebook_name=bundle.target.notebook_name,
            root_path=bundle.target.root_path,
            directory_name=bundle.directory_name,
        )
        try:
            meta_page_id = self._client.create_page(
                directory_id=directory_id, page_name=_METADATA_PAGE_NAME
            )
            self._client.write_page_html(page_id=meta_page_id, html=metadata_html)
            for artifact in bundle.artifacts:
                page_id = self._client.create_page(
                    directory_id=directory_id, page_name=artifact.page_name
                )
                self._client.attach_file(
                    page_id=page_id,
                    filename=artifact.page_name,
                    mime_type=artifact.mime_type,
                    content=artifact.content,
                )
        except Exception as exc:
            # Atomic from the user's view: remove what we created (C-DEST-04).
            with suppress(Exception):
                self._client.delete_directory(directory_id=directory_id)
            raise SnapshotError(
                "Failed to write the snapshot to LabArchives.",
                code="labarchives_write_failed",
                context={"directory": bundle.directory_name},
            ) from exc

        url = self._client.directory_url(directory_id=directory_id)
        return DeliveryReceipt(
            directory_name=bundle.directory_name,
            meta_page_id=meta_page_id,
            meta_page_name=_METADATA_PAGE_NAME,
            page_count=1 + len(bundle.artifacts),
            url=RemoteUrl(url) if url is not None else None,
        )

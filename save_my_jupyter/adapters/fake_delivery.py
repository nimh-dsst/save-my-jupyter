"""In-memory `Delivery` double (target DELIVER). Records every bundle and
returns a plausible receipt without touching LabArchives — used by tests and by
the no-credentials development path."""

from __future__ import annotations

from save_my_jupyter.application.snapshot.notebook_content import NOTEBOOK_MIME_TYPE
from save_my_jupyter.domain.delivery import (
    DeliveryReceipt,
    SnapshotBundle,
)
from save_my_jupyter.domain.types import RemoteUrl

_META_PAGE_NAME = "00 Metadata"
_FAKE_BASE_URL = "https://labarchives.test/snapshots"


class FakeDelivery:
    def __init__(self) -> None:
        self.delivered: list[SnapshotBundle] = []

    def deliver(self, bundle: SnapshotBundle) -> DeliveryReceipt:
        self.delivered.append(bundle)
        meta_page_id = f"meta-{len(self.delivered)}"
        rich_diff_pages = (
            1
            if bundle.metadata.notebook_diff is not None
            and not _has_notebook_artifact(bundle)
            else 0
        )
        # one canonical metadata page plus standalone diff and artifact pages
        page_count = 1 + rich_diff_pages + len(bundle.artifacts)
        return DeliveryReceipt(
            directory_name=bundle.directory_name,
            meta_page_id=meta_page_id,
            meta_page_name=_META_PAGE_NAME,
            page_count=page_count,
            url=RemoteUrl(f"{_FAKE_BASE_URL}/{bundle.directory_name}"),
        )


def _has_notebook_artifact(bundle: SnapshotBundle) -> bool:
    return any(
        artifact.mime_type == NOTEBOOK_MIME_TYPE for artifact in bundle.artifacts
    )

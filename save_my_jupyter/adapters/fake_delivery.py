"""In-memory `Delivery` double (target DELIVER). Records every bundle and
returns a plausible receipt without touching LabArchives — used by tests and by
the no-credentials development path. The real adapter lands in Phase 10."""

from __future__ import annotations

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
        # one canonical metadata page plus one page per artifact (C-DEST-02/03)
        page_count = 1 + len(bundle.artifacts)
        return DeliveryReceipt(
            directory_name=bundle.directory_name,
            meta_page_id=meta_page_id,
            meta_page_name=_META_PAGE_NAME,
            page_count=page_count,
            url=RemoteUrl(f"{_FAKE_BASE_URL}/{bundle.directory_name}"),
        )

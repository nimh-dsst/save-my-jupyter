from __future__ import annotations

from typing import Protocol

from save_my_jupyter.domain.delivery import DeliveryReceipt, SnapshotBundle


class Delivery(Protocol):
    """Persists one snapshot bundle to a destination and returns its receipt.

    Implementations are atomic from the user's perspective (contract C-DEST-04):
    a partial failure cleans up what it created and raises, leaving no receipt.
    """

    def deliver(self, bundle: SnapshotBundle) -> DeliveryReceipt: ...

"""Local filesystem `Delivery` (target DELIVER). Writes each snapshot as a real
folder -- the 00 Metadata page as HTML plus one file per artifact -- under a
configured root, so a demo without LabArchives still produces tangible,
browsable output (and the snapshot directory shows up in the Jupyter file
browser). Atomic: a mid-write failure removes the partial directory (C-DEST-04)."""

from __future__ import annotations

import shutil
from pathlib import Path

from save_my_jupyter.adapters.labarchives.metadata import render_metadata_page
from save_my_jupyter.domain.delivery import DeliveryReceipt, SnapshotBundle
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.types import RemoteUrl

_METADATA_PAGE_NAME = "00 Metadata"


class LocalDelivery:
    def __init__(self, root: Path) -> None:
        self._root = root

    def deliver(self, bundle: SnapshotBundle) -> DeliveryReceipt:
        directory = self._root / bundle.directory_name
        try:
            directory.mkdir(parents=True, exist_ok=False)
            metadata_html = render_metadata_page(
                bundle.metadata,
                artifact_page_names=[a.page_name for a in bundle.artifacts],
            )
            (directory / f"{_METADATA_PAGE_NAME}.html").write_text(
                metadata_html, encoding="utf-8"
            )
            for artifact in bundle.artifacts:
                (directory / _safe_name(artifact.page_name)).write_bytes(
                    artifact.content
                )
        except OSError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise SnapshotError(
                "Failed to write the snapshot to local storage.",
                code="local_delivery_failed",
                context={"directory": bundle.directory_name},
            ) from exc

        return DeliveryReceipt(
            directory_name=bundle.directory_name,
            meta_page_id=_METADATA_PAGE_NAME,
            meta_page_name=_METADATA_PAGE_NAME,
            page_count=1 + len(bundle.artifacts),
            url=RemoteUrl(directory.resolve().as_uri()),
        )


def _safe_name(page_name: str) -> str:
    # Page names are basenames already; guard against any stray separators.
    return page_name.replace("/", "_").replace("\\", "_")

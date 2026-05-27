"""Local filesystem `Delivery` (target DELIVER). Writes each snapshot as a real
folder -- the 00 Metadata page as HTML plus one file per artifact -- under a
configured root, so a demo without LabArchives still produces tangible,
browsable output (and the snapshot directory shows up in the Jupyter file
browser). Atomic: a mid-write failure removes the partial directory (C-DEST-04)."""

from __future__ import annotations

import shutil
from pathlib import Path

from save_my_jupyter.adapters.labarchives.metadata import render_metadata_page
from save_my_jupyter.application.snapshot.notebook_content import NOTEBOOK_MIME_TYPE
from save_my_jupyter.application.snapshot.notebook_render import (
    render_notebook_artifact_html,
)
from save_my_jupyter.domain.delivery import (
    BundleArtifact,
    DeliveryReceipt,
    SnapshotBundle,
)
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
                artifact_page_names=_snapshot_page_names(bundle),
            )
            (directory / f"{_METADATA_PAGE_NAME}.html").write_text(
                metadata_html, encoding="utf-8"
            )
            if bundle.metadata.notebook_diff is not None:
                (
                    directory
                    / f"{_safe_name(bundle.metadata.notebook_diff.page_name)}.html"
                ).write_text(_notebook_diff_html(bundle), encoding="utf-8")
            for artifact in bundle.artifacts:
                artifact_html = _artifact_page_html(artifact)
                if artifact_html is not None:
                    (directory / f"{_safe_name(artifact.page_name)}.html").write_text(
                        artifact_html, encoding="utf-8"
                    )
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
            page_count=1 + len(_snapshot_page_names(bundle)),
            url=RemoteUrl(directory.resolve().as_uri()),
        )


def _snapshot_page_names(bundle: SnapshotBundle) -> list[str]:
    page_names: list[str] = []
    if bundle.metadata.notebook_diff is not None:
        page_names.append(bundle.metadata.notebook_diff.page_name)
    page_names.extend(artifact.page_name for artifact in bundle.artifacts)
    return page_names


def _notebook_diff_html(bundle: SnapshotBundle) -> str:
    notebook_diff = bundle.metadata.notebook_diff
    if notebook_diff is None:
        return ""
    body = "\n".join(entry.html for entry in notebook_diff.entries)
    return f"<h2>{notebook_diff.page_name}</h2>\n<p>{notebook_diff.summary}</p>\n{body}"


def _artifact_page_html(artifact: BundleArtifact) -> str | None:
    if artifact.mime_type != NOTEBOOK_MIME_TYPE:
        return None
    return render_notebook_artifact_html(artifact.page_name, artifact.content)


def _safe_name(page_name: str) -> str:
    # Page names are basenames already; guard against any stray separators.
    return page_name.replace("/", "_").replace("\\", "_")

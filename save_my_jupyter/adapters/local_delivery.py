"""Local filesystem `Delivery` (target DELIVER). Writes each snapshot as a real
folder -- the 00 Metadata page as HTML plus one file per artifact -- under a
configured root, so a demo without LabArchives still produces tangible,
browsable output (and the snapshot directory shows up in the Jupyter file
browser). Atomic: a mid-write failure removes the partial directory (C-DEST-04)."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.labarchives.metadata import render_metadata_page
from save_my_jupyter.application.snapshot.notebook_content import NOTEBOOK_MIME_TYPE
from save_my_jupyter.application.snapshot.notebook_render import (
    render_notebook_artifact_html,
)
from save_my_jupyter.domain.delivery import BundleArtifact, DeliveryReceipt
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.types import RemoteUrl

if TYPE_CHECKING:
    from save_my_jupyter.domain.delivery import NotebookDiff, SnapshotBundle

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
            standalone_diff = _standalone_notebook_diff(bundle)
            if standalone_diff is not None:
                (
                    directory / f"{_safe_name(standalone_diff.page_name)}.html"
                ).write_text(_notebook_diff_html(bundle), encoding="utf-8")
            for artifact in bundle.artifacts:
                artifact_path = _artifact_path(directory, artifact)
                artifact_html = _artifact_page_html(
                    artifact,
                    notebook_diff=_merged_notebook_diff(bundle, artifact),
                )
                if artifact_html is not None:
                    html_path = artifact_path.with_name(f"{artifact_path.name}.html")
                    html_path.parent.mkdir(parents=True, exist_ok=True)
                    html_path.write_text(artifact_html, encoding="utf-8")
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_bytes(artifact.content)
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
    if (notebook_diff := _standalone_notebook_diff(bundle)) is not None:
        page_names.append(notebook_diff.page_name)
    page_names.extend(_artifact_display_name(artifact) for artifact in bundle.artifacts)
    return page_names


def _notebook_diff_html(bundle: SnapshotBundle) -> str:
    notebook_diff = _standalone_notebook_diff(bundle)
    if notebook_diff is None:
        return ""
    body = "\n".join(entry.html for entry in notebook_diff.entries)
    return f"<h2>{notebook_diff.page_name}</h2>\n<p>{notebook_diff.summary}</p>\n{body}"


def _artifact_page_html(
    artifact: BundleArtifact,
    *,
    notebook_diff: NotebookDiff | None = None,
) -> str | None:
    if artifact.mime_type != NOTEBOOK_MIME_TYPE:
        return None
    return render_notebook_artifact_html(
        artifact.page_name,
        artifact.content,
        notebook_diff=notebook_diff,
    )


def _standalone_notebook_diff(bundle: SnapshotBundle) -> NotebookDiff | None:
    if bundle.metadata.notebook_diff is None or _has_notebook_artifact(bundle):
        return None
    return bundle.metadata.notebook_diff


def _merged_notebook_diff(
    bundle: SnapshotBundle, artifact: BundleArtifact
) -> NotebookDiff | None:
    if artifact.mime_type == NOTEBOOK_MIME_TYPE:
        return bundle.metadata.notebook_diff
    return None


def _has_notebook_artifact(bundle: SnapshotBundle) -> bool:
    return any(
        artifact.mime_type == NOTEBOOK_MIME_TYPE for artifact in bundle.artifacts
    )


def _safe_name(page_name: str) -> str:
    # Page names are basenames already; guard against any stray separators.
    return page_name.replace("/", "_").replace("\\", "_")


def _artifact_display_name(artifact: BundleArtifact) -> str:
    return artifact.relative_path or artifact.page_name


def _artifact_path(directory: Path, artifact: BundleArtifact) -> Path:
    relative_path = _safe_relative_path(artifact.relative_path)
    if relative_path is not None:
        return directory / relative_path
    return directory / _safe_name(artifact.page_name)


def _safe_relative_path(value: str | None) -> Path | None:
    if value is None:
        return None
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts:
        return None
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    return Path(*(_safe_name(part) for part in path.parts))

"""LabArchives delivery orchestration (target DELIVER, contracts C-DEST-01..05).
Creates one directory, the canonical 00 Metadata page, then a page per artifact;
on any failure it best-effort moves the directory to API Deleted Items and
raises. Pure orchestration over the LabArchivesClient seam, so it is tested with
a fake; the labapi binding is the only unverifiable part."""

from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import PurePosixPath
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
    from save_my_jupyter.adapters.labarchives.client import LabArchivesClient
    from save_my_jupyter.domain.delivery import NotebookDiff, SnapshotBundle

_METADATA_PAGE_NAME = "00 Metadata"
_LOG = logging.getLogger(__name__)


class LabArchivesDelivery:
    def __init__(self, client: LabArchivesClient) -> None:
        self._client = client

    def deliver(self, bundle: SnapshotBundle) -> DeliveryReceipt:
        directory_id: str | None = None
        operation = "render LabArchives metadata HTML"
        details = _base_error_context(bundle)
        try:
            metadata_html = render_metadata_page(
                bundle.metadata,
                artifact_page_names=_snapshot_page_names(bundle),
            )
            operation = "create LabArchives snapshot directory"
            directory_id = self._client.create_directory(
                notebook_name=bundle.target.notebook_name,
                root_path=bundle.target.root_path,
                directory_name=bundle.directory_name,
            )
            details = {**details, "directory_id": directory_id}
            operation = "create LabArchives metadata page"
            meta_page_id = self._client.create_page(
                directory_id=directory_id, page_name=_METADATA_PAGE_NAME
            )
            operation = "write LabArchives metadata HTML"
            self._client.write_page_html(page_id=meta_page_id, html=metadata_html)
            standalone_diff = _standalone_notebook_diff(bundle)
            if standalone_diff is not None:
                operation = "create LabArchives notebook diff page"
                details = {
                    **details,
                    "diff_page_name": standalone_diff.page_name,
                }
                diff_page_id = self._client.create_page(
                    directory_id=directory_id,
                    page_name=standalone_diff.page_name,
                )
                for entry in standalone_diff.entries:
                    operation = "write LabArchives notebook diff HTML"
                    details = {
                        **details,
                        "diff_page_name": standalone_diff.page_name,
                        "diff_entry_title": entry.title,
                    }
                    self._client.write_page_html(page_id=diff_page_id, html=entry.html)
            for artifact in bundle.artifacts:
                parent_path = _artifact_parent_path(artifact)
                details = _artifact_error_context(
                    bundle=bundle,
                    directory_id=directory_id,
                    artifact=artifact,
                    parent_path=parent_path,
                )
                artifact_directory_id = directory_id
                if parent_path is not None:
                    operation = "ensure LabArchives artifact directory"
                    artifact_directory_id = self._client.ensure_directory_path(
                        parent_directory_id=directory_id,
                        relative_path=parent_path,
                    )
                    details = {
                        **details,
                        "artifact_directory_id": artifact_directory_id,
                    }
                operation = "create LabArchives artifact page"
                page_id = self._client.create_page(
                    directory_id=artifact_directory_id, page_name=artifact.page_name
                )
                details = {**details, "artifact_page_id": page_id}
                operation = "render LabArchives artifact HTML"
                artifact_html = _artifact_page_html(
                    artifact,
                    notebook_diff=_merged_notebook_diff(bundle, artifact),
                )
                if artifact_html is not None:
                    operation = "write LabArchives artifact HTML"
                    self._client.write_page_html(page_id=page_id, html=artifact_html)
                operation = "attach LabArchives artifact file"
                self._client.attach_file(
                    page_id=page_id,
                    filename=artifact.page_name,
                    mime_type=artifact.mime_type,
                    content=artifact.content,
                    description=artifact.description,
                )
        except SnapshotError:
            if directory_id is not None:
                with suppress(Exception):
                    self._client.delete_directory(directory_id=directory_id)
            raise
        except Exception as exc:
            # Atomic from the user's view: remove what we created (C-DEST-04).
            if directory_id is not None:
                with suppress(Exception):
                    self._client.delete_directory(directory_id=directory_id)
            context = _failure_context(
                operation=operation,
                details=details,
                exception=exc,
            )
            _LOG.exception(
                "Save My Jupyter LabArchives write failed: operation=%s context=%s",
                operation,
                context,
            )
            raise SnapshotError(
                _failure_message(operation=operation, exception=exc, details=details),
                code="labarchives_write_failed",
                context=context,
            ) from exc

        url = self._client.directory_url(directory_id=directory_id)
        return DeliveryReceipt(
            directory_name=bundle.directory_name,
            meta_page_id=meta_page_id,
            meta_page_name=_METADATA_PAGE_NAME,
            page_count=1 + len(_snapshot_page_names(bundle)),
            url=RemoteUrl(url) if url is not None else None,
        )


def _snapshot_page_names(bundle: SnapshotBundle) -> list[str]:
    page_names: list[str] = []
    if (notebook_diff := _standalone_notebook_diff(bundle)) is not None:
        page_names.append(notebook_diff.page_name)
    page_names.extend(_artifact_display_name(artifact) for artifact in bundle.artifacts)
    return page_names


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


def _artifact_display_name(artifact: BundleArtifact) -> str:
    return artifact.relative_path or artifact.page_name


def _artifact_parent_path(artifact: BundleArtifact) -> str | None:
    path = _safe_relative_path(artifact.relative_path)
    if path is None or len(path.parts) < 2:
        return None
    return PurePosixPath(*path.parts[:-1]).as_posix()


def _safe_relative_path(value: str | None) -> PurePosixPath | None:
    if value is None:
        return None
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts:
        return None
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def _base_error_context(bundle: SnapshotBundle) -> dict[str, str]:
    return {
        "directory": bundle.directory_name,
        "target_notebook": bundle.target.notebook_name,
        "target_root_path": bundle.target.root_path,
    }


def _artifact_error_context(
    *,
    bundle: SnapshotBundle,
    directory_id: str,
    artifact: BundleArtifact,
    parent_path: str | None,
) -> dict[str, str]:
    context = {
        **_base_error_context(bundle),
        "directory_id": directory_id,
        "artifact_page_name": artifact.page_name,
        "artifact_mime_type": artifact.mime_type,
    }
    if artifact.relative_path:
        context["artifact_relative_path"] = artifact.relative_path
    if parent_path:
        context["artifact_parent_path"] = parent_path
    if artifact.description:
        context["artifact_description"] = artifact.description
    return context


def _failure_context(
    *,
    operation: str,
    details: dict[str, str],
    exception: Exception,
) -> dict[str, str]:
    return {
        **details,
        "operation": operation,
        "exception_type": type(exception).__name__,
        "exception_message": str(exception),
    }


def _failure_message(
    *, operation: str, exception: Exception, details: dict[str, str]
) -> str:
    location = _failure_location(details)
    exception_type = type(exception).__name__
    exception_message = str(exception) or repr(exception)
    return (
        f"LabArchives write failed while trying to {operation}{location}: "
        f"{exception_type}: {exception_message}"
    )


def _failure_location(details: dict[str, str]) -> str:
    if artifact_path := details.get("artifact_relative_path"):
        return f" for artifact {artifact_path!r}"
    if artifact_name := details.get("artifact_page_name"):
        return f" for artifact {artifact_name!r}"
    return f" in snapshot directory {details.get('directory', '<unknown>')!r}"

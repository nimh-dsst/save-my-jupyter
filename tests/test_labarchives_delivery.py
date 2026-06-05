from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from save_my_jupyter.adapters.labarchives.delivery import LabArchivesDelivery
from save_my_jupyter.application.snapshot.build import build_snapshot_bundle
from save_my_jupyter.domain.artifacts import NotebookPayload, WatchedFileArtifact
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import (
    NotebookDiff,
    NotebookDiffEntry,
    SnapshotBundle,
    SnapshotMetadata,
)
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    MimeType,
    SnapshotId,
)

if TYPE_CHECKING:
    from save_my_jupyter.ports import Delivery


class _FakeClient:
    def __init__(
        self,
        *,
        fail_on_attach: bool = False,
        fail_on_attach_filename: str | None = None,
        fail_on_create: bool = False,
        fail_on_ensure_directory: bool = False,
        fail_with_snapshot_error: bool = False,
    ) -> None:
        self.pages: list[str] = []
        self.page_locations: list[tuple[str, str]] = []
        self.directory_paths: list[tuple[str, str]] = []
        self.html_entries: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.attachments: list[str] = []
        self.attachment_pages: list[tuple[str, str]] = []
        self.attachment_descriptions: list[tuple[str, str]] = []
        self._page_names: dict[str, str] = {}
        self._fail_on_attach = fail_on_attach
        self._fail_on_attach_filename = fail_on_attach_filename
        self._fail_on_create = fail_on_create
        self._fail_on_ensure_directory = fail_on_ensure_directory
        self._fail_with_snapshot_error = fail_with_snapshot_error
        self._counter = 0

    def create_directory(
        self, *, notebook_name: str, root_path: str, directory_name: str
    ) -> str:
        if self._fail_on_create:
            raise RuntimeError("create failed")
        return f"dir::{directory_name}"

    def ensure_directory_path(
        self, *, parent_directory_id: str, relative_path: str
    ) -> str:
        if self._fail_on_ensure_directory:
            raise RuntimeError("directory path failed")
        self.directory_paths.append((parent_directory_id, relative_path))
        return f"{parent_directory_id}/{relative_path}"

    def create_page(self, *, directory_id: str, page_name: str) -> str:
        if self._fail_with_snapshot_error:
            raise SnapshotError(
                "LabArchives session expired; sign in again to continue.",
                code="labarchives_session_expired",
            )
        self._counter += 1
        page_id = f"page-{self._counter}"
        self.pages.append(page_name)
        self.page_locations.append((directory_id, page_name))
        self._page_names[page_id] = page_name
        return page_id

    def write_page_html(self, *, page_id: str, html: str) -> None:
        self.html_entries.append((self._page_names[page_id], html))

    def attach_file(
        self,
        *,
        page_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
        description: str | None = None,
    ) -> None:
        del mime_type, content
        if self._fail_on_attach or filename == self._fail_on_attach_filename:
            raise RuntimeError("labarchives attach failed")
        self.attachments.append(filename)
        self.attachment_pages.append((self._page_names[page_id], filename))
        self.attachment_descriptions.append(
            (filename, description if description is not None else filename)
        )

    def delete_directory(self, *, directory_id: str) -> None:
        self.deleted.append(directory_id)

    def directory_url(self, *, directory_id: str) -> str | None:
        return f"https://labarchives.test/{directory_id}"


def _bundle(
    *, notebook_diff: NotebookDiff | None = None, include_notebook: bool = True
) -> SnapshotBundle:
    metadata = SnapshotMetadata(
        notebook_name="nb.ipynb",
        notebook_path="proj/nb.ipynb",
        source=SnapshotSource.MANUAL,
        run_outcome=RunOutcome.NOT_APPLICABLE,
        snapshot_id=SnapshotId("snap-1"),
        run_fingerprint=None,
        trigger_cells=(),
        commit_hash=None,
        commit_status="none",
        commit_url=None,
        diff_included=False,
        extension_version="0.1.0",
        run_label=None,
        tags=(),
        notes=None,
        execution_summary="ok",
        notebook_diff=notebook_diff,
    )
    return build_snapshot_bundle(
        directory_name="2026-05-26T12-00-00.000_snap-1",
        target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
            root_path=LabArchivesRootPath("Notebook Log/a@b.org"),
        ),
        metadata=metadata,
        notebook=NotebookPayload(
            filename="nb.ipynb",
            content=(
                b'{"cells":[{"cell_type":"code","source":"print(1)\\n",'
                b'"outputs":[{"output_type":"stream","name":"stdout",'
                b'"text":"done\\n"}]}]}'
            ),
        )
        if include_notebook
        else None,
        files=(
            WatchedFileArtifact(
                filename="result.csv",
                mime_type=MimeType("text/csv"),
                content=b"a,b",
                relative_path="outputs/session-1/result.csv",
            ),
        ),
    )


def test_successful_delivery_creates_pages_and_returns_receipt() -> None:
    client = _FakeClient()
    delivery: Delivery = LabArchivesDelivery(client)
    receipt = delivery.deliver(_bundle())

    # metadata page + notebook + watched file
    assert client.pages == ["00 Metadata", "nb.ipynb", "result.csv"]
    assert client.directory_paths == [
        ("dir::2026-05-26T12-00-00.000_snap-1", "outputs/session-1")
    ]
    assert (
        "dir::2026-05-26T12-00-00.000_snap-1/outputs/session-1",
        "result.csv",
    ) in client.page_locations
    assert receipt.meta_page_name == "00 Metadata"
    assert receipt.page_count == 3
    assert receipt.directory_name == "2026-05-26T12-00-00.000_snap-1"
    assert receipt.url is not None
    assert client.deleted == []


def test_delivery_writes_readable_notebook_page_html() -> None:
    client = _FakeClient()
    delivery: Delivery = LabArchivesDelivery(client)

    delivery.deliver(_bundle())

    notebook_entries = [
        html for page_name, html in client.html_entries if page_name == "nb.ipynb"
    ]
    assert len(notebook_entries) == 1
    assert "Notebook nb.ipynb" in notebook_entries[0]
    assert "Cell 1 (code)" in notebook_entries[0]
    assert "print" in notebook_entries[0]
    assert "1" in notebook_entries[0]
    assert "stream (stdout)" in notebook_entries[0]
    assert "done" in notebook_entries[0]
    assert client.attachments == ["nb.ipynb", "result.csv"]


def test_delivery_lists_watched_file_relative_path_in_metadata() -> None:
    client = _FakeClient()
    delivery: Delivery = LabArchivesDelivery(client)

    delivery.deliver(_bundle())

    metadata_entries = [
        html for page_name, html in client.html_entries if page_name == "00 Metadata"
    ]
    assert len(metadata_entries) == 1
    assert "outputs/session-1/result.csv" in metadata_entries[0]


def test_delivery_merges_rich_notebook_diff_into_notebook_page() -> None:
    client = _FakeClient()
    delivery: Delivery = LabArchivesDelivery(client)
    notebook_diff = NotebookDiff(
        page_name="01 Notebook Diff",
        summary="1 of 2 cells changed.",
        entries=(
            NotebookDiffEntry(
                title="Cell 1 changed",
                cell_index=0,
                status="changed",
                source_diff_html=(
                    '<pre><span style="background:#ffebe9;">-x = 1</span>'
                    '<span style="background:#e6ffed;">+x = 2</span></pre>'
                ),
                html=(
                    "<section>"
                    "<h3>Cell 1 changed</h3>"
                    '<span style="background:#ffebe9;">-x = 1</span>'
                    '<span style="background:#e6ffed;">+x = 2</span>'
                    "</section>"
                ),
            ),
            NotebookDiffEntry(
                title="Cell 2",
                html="<section><h3>Cell 2</h3><pre>unchanged()</pre></section>",
            ),
        ),
    )

    receipt = delivery.deliver(_bundle(notebook_diff=notebook_diff))

    assert client.pages == ["00 Metadata", "nb.ipynb", "result.csv"]
    cell_entries = [
        html for page_name, html in client.html_entries if page_name == "nb.ipynb"
    ]
    assert len(cell_entries) == 1
    assert "Notebook nb.ipynb" in cell_entries[0]
    assert "1 of 2 cells changed." in cell_entries[0]
    assert "Cell 1 changed" in cell_entries[0]
    assert "-x = 1" in cell_entries[0]
    assert "+x = 2" in cell_entries[0]
    assert "background:#ffebe9" in cell_entries[0]
    assert "background:#e6ffed" in cell_entries[0]
    assert "Cell 2" in cell_entries[0]
    assert ("nb.ipynb", "nb.ipynb") in client.attachment_pages
    assert receipt.page_count == 3


def test_delivery_keeps_standalone_diff_page_when_notebook_is_not_included() -> None:
    client = _FakeClient()
    delivery: Delivery = LabArchivesDelivery(client)
    notebook_diff = NotebookDiff(
        page_name="01 Notebook Diff",
        summary="1 of 1 cells changed.",
        entries=(
            NotebookDiffEntry(
                title="Cell 1 changed",
                html="<section><h3>Cell 1 changed</h3></section>",
            ),
        ),
    )

    receipt = delivery.deliver(
        _bundle(notebook_diff=notebook_diff, include_notebook=False)
    )

    assert client.pages == ["00 Metadata", "01 Notebook Diff", "result.csv"]
    assert any(
        page_name == "01 Notebook Diff" and "Cell 1 changed" in html
        for page_name, html in client.html_entries
    )
    assert receipt.page_count == 3


def test_failed_delivery_cleans_up_and_raises() -> None:
    client = _FakeClient(fail_on_attach_filename="result.csv")
    delivery = LabArchivesDelivery(client)
    with pytest.raises(SnapshotError) as exc:
        delivery.deliver(_bundle())
    assert exc.value.code == "labarchives_write_failed"
    assert str(exc.value) == (
        "LabArchives write failed while trying to attach LabArchives artifact file "
        "for artifact 'outputs/session-1/result.csv': RuntimeError: "
        "labarchives attach failed"
    )
    assert exc.value.context["operation"] == "attach LabArchives artifact file"
    assert exc.value.context["artifact_relative_path"] == (
        "outputs/session-1/result.csv"
    )
    assert exc.value.context["artifact_parent_path"] == "outputs/session-1"
    assert exc.value.context["exception_type"] == "RuntimeError"
    assert exc.value.context["exception_message"] == "labarchives attach failed"
    # best-effort cleanup moved the directory to API Deleted Items
    assert client.deleted == ["dir::2026-05-26T12-00-00.000_snap-1"]


def test_directory_path_failure_reports_artifact_parent_path() -> None:
    client = _FakeClient(fail_on_ensure_directory=True)
    delivery = LabArchivesDelivery(client)
    with pytest.raises(SnapshotError) as exc:
        delivery.deliver(_bundle())

    assert exc.value.code == "labarchives_write_failed"
    assert "ensure LabArchives artifact directory" in str(exc.value)
    assert "outputs/session-1/result.csv" in str(exc.value)
    assert "RuntimeError: directory path failed" in str(exc.value)
    assert exc.value.context["operation"] == "ensure LabArchives artifact directory"
    assert exc.value.context["artifact_parent_path"] == "outputs/session-1"


def test_directory_create_failure_is_wrapped_without_cleanup() -> None:
    client = _FakeClient(fail_on_create=True)
    delivery = LabArchivesDelivery(client)
    with pytest.raises(SnapshotError) as exc:
        delivery.deliver(_bundle())
    assert exc.value.code == "labarchives_write_failed"
    assert "create LabArchives snapshot directory" in str(exc.value)
    assert exc.value.context["operation"] == "create LabArchives snapshot directory"
    assert exc.value.context["exception_message"] == "create failed"
    assert client.deleted == []


def test_delivery_preserves_snapshot_error_after_cleanup() -> None:
    client = _FakeClient(fail_with_snapshot_error=True)
    delivery = LabArchivesDelivery(client)
    with pytest.raises(SnapshotError) as exc:
        delivery.deliver(_bundle())
    assert exc.value.code == "labarchives_session_expired"
    assert client.deleted == ["dir::2026-05-26T12-00-00.000_snap-1"]

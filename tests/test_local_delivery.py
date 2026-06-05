from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.local_delivery import LocalDelivery
from save_my_jupyter.application.snapshot.build import build_snapshot_bundle
from save_my_jupyter.domain.artifacts import (
    FigureArtifact,
    NotebookPayload,
    WatchedFileArtifact,
)
from save_my_jupyter.domain.config import LabArchivesTarget
from save_my_jupyter.domain.delivery import (
    NotebookDiff,
    NotebookDiffEntry,
    SnapshotBundle,
    SnapshotMetadata,
)
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    LabArchivesNotebookName,
    LabArchivesRootPath,
    MimeType,
    SnapshotId,
)

if TYPE_CHECKING:
    from save_my_jupyter.ports import Delivery


_NOTEBOOK_WITH_IMAGE = (
    b'{"cells":[{"cell_type":"code","source":"plot()\\n","outputs":['
    b'{"output_type":"display_data","data":{"image/png":"UE5H"}}]}]}'
)


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
            root_path=LabArchivesRootPath("Notebook Log"),
        ),
        metadata=metadata,
        notebook=(
            NotebookPayload(filename="nb.ipynb", content=_NOTEBOOK_WITH_IMAGE)
            if include_notebook
            else None
        ),
        figures=(
            FigureArtifact(
                name="figure-001.png", mime_type=MimeType("image/png"), content=b"PNG"
            ),
        ),
    )


def test_writes_snapshot_directory_with_pages_and_metadata(tmp_path: Path) -> None:
    delivery: Delivery = LocalDelivery(tmp_path)
    receipt = delivery.deliver(_bundle())

    directory = tmp_path / "2026-05-26T12-00-00.000_snap-1"
    assert (directory / "00 Metadata.html").is_file()
    assert "Snapshot metadata" in (directory / "00 Metadata.html").read_text("utf-8")
    assert (directory / "nb.ipynb").read_bytes() == _NOTEBOOK_WITH_IMAGE
    assert (directory / "nb.ipynb.html").is_file()
    notebook_html = (directory / "nb.ipynb.html").read_text("utf-8")
    assert "Notebook nb.ipynb" in notebook_html
    assert "data:image/png;base64,UE5H" in notebook_html
    assert not (directory / "figure-001.png").exists()

    assert receipt.meta_page_name == "00 Metadata"
    assert receipt.page_count == 2  # metadata + notebook with inline figures
    assert receipt.url is not None
    assert receipt.url.startswith("file:")


def test_each_snapshot_gets_its_own_directory(tmp_path: Path) -> None:
    delivery = LocalDelivery(tmp_path)
    delivery.deliver(_bundle())
    directories = sorted(child.name for child in tmp_path.iterdir() if child.is_dir())
    assert directories == ["2026-05-26T12-00-00.000_snap-1"]


def test_watched_files_are_written_relative_to_capture_root(tmp_path: Path) -> None:
    delivery: Delivery = LocalDelivery(tmp_path)
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
    )
    bundle = build_snapshot_bundle(
        directory_name="2026-05-26T12-00-00.000_snap-1",
        target=LabArchivesTarget(
            notebook_name=LabArchivesNotebookName("Jupyter Snapshots"),
            root_path=LabArchivesRootPath("Notebook Log"),
        ),
        metadata=metadata,
        notebook=None,
        files=(
            WatchedFileArtifact(
                filename="result.csv",
                mime_type=MimeType("text/csv"),
                content=b"a,b",
                relative_path="outputs/session-1/result.csv",
            ),
        ),
    )

    delivery.deliver(bundle)

    directory = tmp_path / "2026-05-26T12-00-00.000_snap-1"
    assert (directory / "outputs" / "session-1" / "result.csv").read_bytes() == b"a,b"
    assert not (directory / "result.csv").exists()
    metadata_html = (directory / "00 Metadata.html").read_text("utf-8")
    assert "outputs/session-1/result.csv" in metadata_html


def test_rich_diff_is_merged_into_readable_notebook_page(tmp_path: Path) -> None:
    delivery: Delivery = LocalDelivery(tmp_path)
    notebook_diff = NotebookDiff(
        page_name="01 Notebook Diff",
        summary="1 of 1 cells changed.",
        entries=(
            NotebookDiffEntry(
                title="Cell 1 changed",
                html="<section>Cell 1 changed</section>",
            ),
        ),
    )

    receipt = delivery.deliver(_bundle(notebook_diff=notebook_diff))

    directory = tmp_path / "2026-05-26T12-00-00.000_snap-1"
    assert not (directory / "01 Notebook Diff.html").exists()
    assert (directory / "nb.ipynb").is_file()
    assert (directory / "nb.ipynb.html").is_file()
    notebook_html = (directory / "nb.ipynb.html").read_text("utf-8")
    assert "Notebook nb.ipynb" in notebook_html
    assert "1 of 1 cells changed." in notebook_html
    assert "Cell 1 changed" in notebook_html
    assert not (directory / "figure-001.png").exists()
    assert receipt.page_count == 2  # metadata + notebook page with merged diff


def test_rich_diff_stays_separate_when_notebook_page_is_absent(
    tmp_path: Path,
) -> None:
    delivery: Delivery = LocalDelivery(tmp_path)
    notebook_diff = NotebookDiff(
        page_name="01 Notebook Diff",
        summary="1 of 1 cells changed.",
        entries=(
            NotebookDiffEntry(
                title="Cell 1 changed",
                html="<section>Cell 1 changed</section>",
            ),
        ),
    )

    receipt = delivery.deliver(
        _bundle(notebook_diff=notebook_diff, include_notebook=False)
    )

    directory = tmp_path / "2026-05-26T12-00-00.000_snap-1"
    assert (directory / "01 Notebook Diff.html").is_file()
    assert "Cell 1 changed" in (directory / "01 Notebook Diff.html").read_text("utf-8")
    assert not (directory / "nb.ipynb.html").exists()
    assert receipt.page_count == 3  # metadata + diff page + extracted figure

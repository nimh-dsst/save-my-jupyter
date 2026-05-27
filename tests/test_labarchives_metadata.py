from __future__ import annotations

from save_my_jupyter.adapters.labarchives.metadata import render_metadata_page
from save_my_jupyter.domain.delivery import SnapshotMetadata
from save_my_jupyter.domain.enums import SnapshotSource
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import CellId, CommitHash, RemoteUrl, SnapshotId


def _metadata(**overrides: object) -> SnapshotMetadata:
    base: dict[str, object] = {
        "notebook_name": "analysis.ipynb",
        "notebook_path": "analysis/analysis.ipynb",
        "source": SnapshotSource.TRIGGER_CELL,
        "run_outcome": RunOutcome.ERROR,
        "snapshot_id": SnapshotId("snap-1"),
        "run_fingerprint": None,
        "trigger_cells": (CellId("cell-1"), CellId("cell-2")),
        "commit_hash": CommitHash("abcdef1234567890"),
        "commit_status": "created",
        "commit_url": RemoteUrl("https://github.com/o/r/commit/abcdef1234567890"),
        "diff_included": True,
        "extension_version": "0.1.0",
        "run_label": "training-3",
        "tags": ("baseline", "gpu"),
        "notes": "a note",
        "execution_summary": "final value",
    }
    base.update(overrides)
    return SnapshotMetadata(**base)  # type: ignore[arg-type]


def test_metadata_page_includes_all_contract_fields() -> None:
    html = render_metadata_page(_metadata(), artifact_page_names=["analysis.ipynb"])
    for label in (
        "Notebook",
        "Notebook path",
        "Source",
        "Run outcome",
        "Snapshot ID",
        "Run fingerprint",
        "Trigger cells",
        "Commit hash",
        "Commit status",
        "Commit URL",
        "Diff included",
        "Extension version",
        "Run label",
        "Notes",
    ):
        assert label in html
    assert "analysis.ipynb" in html
    assert "training-3" in html
    assert "trigger_cell" in html
    assert "error" in html
    assert "cell-1, cell-2" in html


def test_tags_row_is_explicitly_labeled_as_metadata_text() -> None:
    html = render_metadata_page(_metadata(), artifact_page_names=[])
    assert "Tags (metadata text, not native LabArchives tags)" in html
    assert "baseline, gpu" in html


def test_diff_included_renders_yes_or_no() -> None:
    assert "Yes" in render_metadata_page(
        _metadata(diff_included=True), artifact_page_names=[]
    )
    assert "No" in render_metadata_page(
        _metadata(diff_included=False), artifact_page_names=[]
    )


def test_artifacts_index_lists_pages() -> None:
    html = render_metadata_page(
        _metadata(), artifact_page_names=["analysis.ipynb", "figure-001.png"]
    )
    assert "Artifacts" in html
    assert "figure-001.png" in html


def test_html_is_escaped() -> None:
    html = render_metadata_page(
        _metadata(notes="<script>alert(1)</script>"), artifact_page_names=[]
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_missing_optional_fields_render_a_dash() -> None:
    html = render_metadata_page(
        _metadata(run_fingerprint=None, commit_hash=None, commit_url=None, notes=None),
        artifact_page_names=[],
    )
    assert "&mdash;" in html

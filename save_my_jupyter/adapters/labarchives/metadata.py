"""Pure rendering of the `00 Metadata` page HTML (contract C-DEST-02). No IO;
the delivery client uploads the returned HTML. All interpolated values are
HTML-escaped."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from save_my_jupyter.domain.delivery import SnapshotMetadata

_DASH = "&mdash;"
_TAGS_LABEL = "Tags"


def render_metadata_page(
    metadata: SnapshotMetadata, *, artifact_page_names: Sequence[str]
) -> str:
    rows = [
        ("Notebook", metadata.notebook_name),
        ("Notebook path", metadata.notebook_path),
        ("Source", metadata.source.value),
        ("Run outcome", metadata.run_outcome.value),
        ("Snapshot ID", metadata.snapshot_id),
        ("Run fingerprint", metadata.run_fingerprint),
        ("Trigger cells", ", ".join(metadata.trigger_cells) or None),
        ("Commit hash", metadata.commit_hash),
        ("Commit status", metadata.commit_status),
        ("Commit URL", metadata.commit_url),
        ("Diff included", "Yes" if metadata.diff_included else "No"),
        ("Notebook diff", _notebook_diff_summary(metadata, artifact_page_names)),
        ("Extension version", metadata.extension_version),
        ("Run label", metadata.run_label),
        (_TAGS_LABEL, ", ".join(metadata.tags) or None),
        ("Notes", metadata.notes),
        *_extra_field_rows(metadata.extra_fields),
    ]
    table_rows = "\n".join(_render_row(label, value) for label, value in rows)
    return (
        "<h2>Snapshot metadata</h2>\n"
        f"<table>\n{table_rows}\n</table>\n"
        f"{_render_summary(metadata.execution_summary)}\n"
        f"{_render_working_tree_diff(metadata.working_tree_diff)}\n"
        f"{_render_artifacts(artifact_page_names)}"
    )


def _render_row(label: str, value: str | None) -> str:
    rendered = escape(value) if value else _DASH
    return f"<tr><th>{escape(label)}</th><td>{rendered}</td></tr>"


def _render_summary(summary: str) -> str:
    return f"<h3>Execution summary</h3>\n<pre>{escape(summary)}</pre>"


def _render_working_tree_diff(diff_text: str | None) -> str:
    if not diff_text:
        return ""
    return f"<h3>Working tree diff</h3>\n<pre>{escape(diff_text)}</pre>"


def _extra_field_rows(fields: Mapping[str, str]) -> list[tuple[str, str]]:
    return [(f"Metadata: {key}", value) for key, value in fields.items()]


def _notebook_diff_summary(
    metadata: SnapshotMetadata, artifact_page_names: Sequence[str]
) -> str | None:
    if metadata.notebook_diff is None:
        return None
    page_name = _notebook_diff_page_name(metadata, artifact_page_names)
    return f"{metadata.notebook_diff.summary} See {page_name}."


def _notebook_diff_page_name(
    metadata: SnapshotMetadata, artifact_page_names: Sequence[str]
) -> str:
    if metadata.notebook_name in artifact_page_names:
        return metadata.notebook_name
    notebook_page = next(
        (name for name in artifact_page_names if name.lower().endswith(".ipynb")),
        None,
    )
    if notebook_page is not None:
        return notebook_page
    if metadata.notebook_diff is None:
        return metadata.notebook_name
    return metadata.notebook_diff.page_name


def _render_artifacts(page_names: Sequence[str]) -> str:
    if not page_names:
        return "<h3>Artifacts</h3>\n<p>No additional artifacts.</p>"
    items = "\n".join(f"<li>{escape(name)}</li>" for name in page_names)
    return f"<h3>Artifacts</h3>\n<ul>\n{items}\n</ul>"

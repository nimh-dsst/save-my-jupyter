from __future__ import annotations

import builtins
import csv
import difflib
import json
import keyword
import re
import token
import tokenize
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from html import escape
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import labapi

from save_my_jupyter.adapters.path_templates import render_root_path_template
from save_my_jupyter.domain import (
    ArtifactRef,
    DiffArtifact,
    FigureArtifact,
    FileArtifact,
    NotebookArtifact,
    SnapshotFailed,
    SnapshotPersisted,
    SnapshotPersistenceResult,
    SnapshotRecord,
)
from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.notebook.diff import NotebookCellChange, build_notebook_diff
from save_my_jupyter.services.auth import LabArchivesSession

_DIFF_PATH_PATTERN = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_IMAGE_SUFFIXES = frozenset(
    {
        ".avif",
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    }
)
_NO_EXECUTION_SUMMARY = "(no execution summary available)"
_DIFF_DESCRIPTION = (
    "Filtered working tree patch; notebook JSON and image patches are omitted"
)
_METADATA_PAGE_NAME = "00 Metadata"
_NOTEBOOK_DESCRIPTION = "Notebook snapshot"
_FILE_DESCRIPTION = "File artifact"
_PAGE_NAME_MAX_LENGTH = 120
_TEXT_PREVIEW_MAX_BYTES = 200_000
_CSV_PREVIEW_MAX_ROWS = 100
_CSV_PREVIEW_MAX_COLUMNS = 20
_PYTHON_BUILTINS = frozenset(dir(builtins))


class LabArchivesAdapter:
    def write_snapshot(
        self,
        record: SnapshotRecord,
        session: LabArchivesSession,
    ) -> SnapshotPersistenceResult:
        directory_name = _format_page_name(record)
        created_pages: list[Any] = []
        snapshot_directory: Any | None = None
        try:
            snapshot_directory = _create_snapshot_directory(
                record,
                session,
                directory_name,
            )
            page_plan = _build_page_plan(record)
            metadata_page = _create_snapshot_page(
                snapshot_directory,
                _METADATA_PAGE_NAME,
            )
            created_pages.append(metadata_page)
            _populate_metadata_page(metadata_page, record, page_plan.artifact_pages)

            for notebook_page in page_plan.notebook_pages:
                page = _create_snapshot_page(snapshot_directory, notebook_page.name)
                created_pages.append(page)
                _populate_notebook_page(page, record, notebook_page)

            for file_page in page_plan.file_pages:
                page = _create_snapshot_page(snapshot_directory, file_page.name)
                created_pages.append(page)
                _populate_file_page(page, record, file_page.artifact)
        except labapi.AuthenticationError as exc:
            _attempt_pages_cleanup(created_pages)
            _attempt_directory_cleanup(snapshot_directory)
            return SnapshotFailed(
                error_code="labarchives_session_expired",
                message=(
                    f"LabArchives session expired; sign in again to continue. ({exc})"
                ),
            )
        except Exception as exc:
            _attempt_pages_cleanup(created_pages)
            _attempt_directory_cleanup(snapshot_directory)
            return SnapshotFailed(
                error_code="labarchives_write_failed",
                message=str(exc),
            )

        metadata_page = created_pages[0]
        return SnapshotPersisted(
            snapshot_id=record.snapshot_id,
            labarchives_page_id=metadata_page.id,
            labarchives_page_name=_METADATA_PAGE_NAME,
            labarchives_directory_name=directory_name,
            labarchives_meta_page_id=metadata_page.id,
            labarchives_meta_page_name=_METADATA_PAGE_NAME,
            labarchives_page_count=len(created_pages),
        )


@dataclass(frozen=True, slots=True)
class _NotebookPagePlan:
    name: str
    display_name: str
    relative_path: str
    artifact: NotebookArtifact | None
    figures: tuple[FigureArtifact, ...]


@dataclass(frozen=True, slots=True)
class _FilePagePlan:
    name: str
    artifact: FileArtifact


@dataclass(frozen=True, slots=True)
class _ArtifactPageReference:
    artifact: ArtifactRef
    page_name: str


@dataclass(frozen=True, slots=True)
class _PagePlan:
    notebook_pages: tuple[_NotebookPagePlan, ...]
    file_pages: tuple[_FilePagePlan, ...]
    artifact_pages: tuple[_ArtifactPageReference, ...]


def _attempt_page_cleanup(page: Any) -> None:
    with suppress(Exception):
        page.delete()


def _attempt_pages_cleanup(pages: list[Any]) -> None:
    for page in reversed(pages):
        _attempt_page_cleanup(page)


def _attempt_directory_cleanup(directory: Any | None) -> None:
    if directory is None:
        return
    with suppress(Exception):
        directory.delete()


@dataclass(frozen=True, slots=True)
class _PatchSection:
    relative_path: str
    status: str
    display_lines: tuple[str, ...]


def _create_snapshot_directory(
    record: SnapshotRecord,
    session: LabArchivesSession,
    directory_name: str,
) -> Any:
    directory = session.user.notebooks[str(record.labarchives_target.notebook_name)]
    for path_segment in render_root_path_template(
        str(record.labarchives_target.root_path),
        record,
        session,
    ):
        directory = directory.dir(path_segment)
    return directory.create(
        labapi.NotebookDirectory,
        directory_name,
        if_exists=labapi.InsertBehavior.Raise,
    )


def _create_snapshot_page(directory: Any, page_name: str) -> Any:
    return directory.create(
        labapi.NotebookPage,
        page_name,
        if_exists=labapi.InsertBehavior.Raise,
    )


def _format_page_name(record: SnapshotRecord) -> str:
    timestamp_part = record.timestamp.isoformat(timespec="milliseconds").replace(
        ":", "-"
    )
    suffix = str(record.snapshot_id)[:12] or "snapshot"
    return f"{timestamp_part}_{suffix}"


def _build_page_plan(record: SnapshotRecord) -> _PagePlan:
    notebook_artifacts = _notebook_artifacts(record.artifacts)
    figure_artifacts = _figure_artifacts(record.artifacts)
    file_artifacts = _file_artifacts(record.artifacts)

    notebook_pages: list[_NotebookPagePlan] = []
    page_number = 1
    if notebook_artifacts:
        for notebook_artifact in notebook_artifacts:
            notebook_pages.append(
                _NotebookPagePlan(
                    name=_format_child_page_name(
                        page_number,
                        "Notebook",
                        notebook_artifact.display_name,
                    ),
                    display_name=notebook_artifact.display_name,
                    relative_path=_artifact_relative_path(notebook_artifact),
                    artifact=notebook_artifact,
                    figures=(),
                )
            )
            page_number += 1
    else:
        notebook_pages.append(
            _NotebookPagePlan(
                name=_format_child_page_name(
                    page_number,
                    "Notebook",
                    record.notebook_context.notebook_name,
                ),
                display_name=record.notebook_context.notebook_name,
                relative_path=_notebook_path(record),
                artifact=None,
                figures=(),
            )
        )
        page_number += 1

    if notebook_pages:
        first_notebook = notebook_pages[0]
        notebook_pages[0] = _NotebookPagePlan(
            name=first_notebook.name,
            display_name=first_notebook.display_name,
            relative_path=first_notebook.relative_path,
            artifact=first_notebook.artifact,
            figures=figure_artifacts,
        )

    file_pages = [
        _FilePagePlan(
            name=_format_child_page_name(
                page_number + index,
                "File",
                _file_page_label(artifact),
            ),
            artifact=artifact,
        )
        for index, artifact in enumerate(file_artifacts)
    ]

    artifact_pages: list[_ArtifactPageReference] = []
    for notebook_page in notebook_pages:
        if notebook_page.artifact is not None:
            artifact_pages.append(
                _ArtifactPageReference(
                    artifact=notebook_page.artifact,
                    page_name=notebook_page.name,
                )
            )
        for figure in notebook_page.figures:
            artifact_pages.append(
                _ArtifactPageReference(
                    artifact=figure,
                    page_name=notebook_page.name,
                )
            )
    artifact_pages.extend(
        _ArtifactPageReference(artifact=file_page.artifact, page_name=file_page.name)
        for file_page in file_pages
    )
    artifact_pages.extend(
        _ArtifactPageReference(artifact=artifact, page_name=_METADATA_PAGE_NAME)
        for artifact in _diff_artifacts(record.artifacts)
    )
    return _PagePlan(
        notebook_pages=tuple(notebook_pages),
        file_pages=tuple(file_pages),
        artifact_pages=tuple(artifact_pages),
    )


def _format_child_page_name(position: int, label: str, raw_name: str) -> str:
    prefix = f"{position:02} {label} - "
    available_length = _PAGE_NAME_MAX_LENGTH - len(prefix)
    safe_name = _sanitize_page_name_fragment(raw_name)
    if len(safe_name) > available_length:
        safe_name = safe_name[:available_length].rstrip(" .-_") or label
    return f"{prefix}{safe_name}"


def _sanitize_page_name_fragment(value: str) -> str:
    normalized = value.replace("\\", " - ").replace("/", " - ")
    normalized = re.sub(r"[\x00-\x1f:*?\"<>|]+", " - ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .-_")
    return normalized or "artifact"


def _populate_metadata_page(
    page: Any,
    record: SnapshotRecord,
    artifact_pages: tuple[_ArtifactPageReference, ...],
) -> None:
    entries = page.entries
    for entry_type, content in _iter_metadata_entries(record, artifact_pages):
        entries.create(entry_type, content)

    for artifact in _diff_artifacts(record.artifacts):
        entries.create(labapi.AttachmentEntry, _attachment_entry(artifact))


def _populate_notebook_page(
    page: Any,
    record: SnapshotRecord,
    notebook_page: _NotebookPagePlan,
) -> None:
    entries = page.entries
    entries.create(labapi.TextEntry, _notebook_page_rich_text(record, notebook_page))
    if notebook_page.artifact is not None:
        entries.create(
            labapi.AttachmentEntry, _attachment_entry(notebook_page.artifact)
        )
    for figure in notebook_page.figures:
        entries.create(labapi.AttachmentEntry, _attachment_entry(figure))


def _populate_file_page(
    page: Any, record: SnapshotRecord, artifact: FileArtifact
) -> None:
    entries = page.entries
    payload, description = _attachment_content(artifact)
    entries.create(labapi.TextEntry, _file_page_rich_text(record, artifact, payload))
    entries.create(
        labapi.AttachmentEntry,
        _attachment_entry_from_content(artifact, payload, description),
    )


def _iter_metadata_entries(
    record: SnapshotRecord,
    artifact_pages: tuple[_ArtifactPageReference, ...],
) -> Iterator[tuple[type[object], str]]:
    yield labapi.TextEntry, _metadata_rich_text(record, artifact_pages)
    yield labapi.PlainTextEntry, _repo_summary(record)
    yield (
        labapi.PlainTextEntry,
        (record.produced_value_summary or _NO_EXECUTION_SUMMARY),
    )

    if record.dirty_diff is not None:
        yield labapi.TextEntry, _diff_rich_text(record)


def _metadata_rich_text(
    record: SnapshotRecord,
    artifact_pages: tuple[_ArtifactPageReference, ...],
) -> str:
    return "".join(
        [
            _html_section(
                "Snapshot Metadata",
                _html_rows_table(
                    [
                        ("Notebook", _html_text(record.notebook_context.notebook_name)),
                        ("Notebook path", _html_text(_notebook_path(record))),
                        ("Source", _html_text(record.source.value)),
                        ("Snapshot ID", _html_text(str(record.snapshot_id))),
                        ("Run fingerprint", _html_text(str(record.run_fingerprint))),
                        (
                            "Trigger cells",
                            _html_text(_format_string_list(record.trigger_cell_ids)),
                        ),
                        (
                            "Commit hash",
                            _html_text(_format_commit_hash(record.commit_hash)),
                        ),
                        (
                            "Commit status",
                            _html_text(_format_commit_status(record)),
                        ),
                        ("Commit URL", _html_text(record.commit_url or "(none)")),
                        (
                            "Diff included",
                            _html_text(_format_yes_no(record.dirty_diff is not None)),
                        ),
                        ("Extension version", _html_text(record.extension_version)),
                        (
                            "Run label",
                            _html_text(
                                _format_optional_text(record.metadata.run_label)
                            ),
                        ),
                        (
                            "Experiment context",
                            _html_text(
                                _format_optional_text(
                                    record.metadata.experiment_context
                                )
                            ),
                        ),
                        (
                            "Tags (metadata text, not native LabArchives tags)",
                            _html_text(_format_string_list(record.metadata.tags)),
                        ),
                        (
                            "Notes",
                            _html_text(
                                _format_optional_text(record.metadata.notes),
                                preserve_lines=True,
                            ),
                        ),
                    ]
                ),
            ),
            _html_section(
                "Extra Fields",
                _html_rows_table(
                    [
                        (str(key), _html_text(str(value)))
                        for key, value in sorted(record.metadata.extra_fields.items())
                    ]
                ),
            ),
            _html_section(
                "Artifacts",
                _html_artifacts_table(record.artifacts, artifact_pages),
            ),
        ]
    )


def _html_section(title: str, body: str) -> str:
    return f"<p><strong>{escape(title)}</strong></p>{body}"


def _html_rows_table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p>(none)</p>"
    rendered_rows = "".join(
        [
            f"<tr><td><strong>{escape(label)}</strong></td><td>{value}</td></tr>"
            for label, value in rows
        ]
    )
    return f"<table><tbody>{rendered_rows}</tbody></table>"


def _html_artifacts_table(
    artifacts: tuple[ArtifactRef, ...],
    artifact_pages: tuple[_ArtifactPageReference, ...],
) -> str:
    if not artifacts:
        return "<p>(none)</p>"
    rendered_rows = "".join(
        [
            "<tr>"
            f"<td>{_html_text(artifact.display_name)}</td>"
            f"<td>{_html_text(artifact.kind.value)}</td>"
            f"<td>{_html_text(_artifact_relative_path(artifact))}</td>"
            f"<td>{_html_text(_artifact_page_name(artifact, artifact_pages))}</td>"
            "</tr>"
            for artifact in artifacts
        ]
    )
    return (
        "<table><thead><tr><th>Name</th><th>Type</th><th>Path</th>"
        "<th>LabArchives page</th></tr></thead>"
        f"<tbody>{rendered_rows}</tbody></table>"
    )


def _html_text(value: str, *, preserve_lines: bool = False) -> str:
    escaped = escape(value)
    if preserve_lines:
        return escaped.replace("\n", "<br/>")
    return escaped


def _html_pre(value: str) -> str:
    return f'<pre style="white-space:pre-wrap;">{escape(value)}</pre>'


def _repo_summary(record: SnapshotRecord) -> str:
    rows = [
        ("Repository", _repository_name(record)),
        (
            "Repository root",
            (
                str(record.repo.repo_root)
                if record.repo.repo_root is not None
                else "(none)"
            ),
        ),
        ("Notebook path", _notebook_path(record)),
        ("Remote", str(record.repo.remote_url) if record.repo.remote_url else "(none)"),
        ("Working tree", _working_tree_status(record)),
        ("HEAD", _format_commit_hash(record.repo.head_commit)),
        ("Snapshot commit", _format_commit_hash(record.commit_hash)),
        ("Commit status", _format_commit_status(record)),
        ("Commit URL", record.commit_url or "(none)"),
    ]
    return "\n".join(["Git Summary", "", *_format_rows(rows)])


def _diff_rich_text(record: SnapshotRecord) -> str:
    diff_text = record.dirty_diff
    if diff_text is None:
        return ""
    rows = [
        ("Repository", _repository_name(record)),
        ("Notebook path", _notebook_path(record)),
        ("Compared against", "Pre-snapshot HEAD"),
        (
            "Scope",
            (
                "Notebook and configured watched paths only; rich notebook diff "
                "omits raw notebook JSON and image patches"
            ),
        ),
    ]
    if record.commit_hash is not None:
        rows.append(("Snapshot commit", _format_commit_hash(record.commit_hash)))
    sections = [_html_rows_table([(label, _html_text(value)) for label, value in rows])]

    notebook_section = _notebook_diff_section(record)
    rendered_notebook_path = str(
        record.repo.relative_notebook_path or record.notebook_context.notebook_path
    )
    if notebook_section is not None:
        sections.append(notebook_section)

    file_sections = [
        _file_diff_section(section)
        for section in _parse_patch_sections(diff_text)
        if section.relative_path != rendered_notebook_path
        and not section.relative_path.endswith(".ipynb")
        and not _is_image_path(section.relative_path)
    ]
    if file_sections:
        sections.extend(file_sections)

    if len(sections) == 1:
        sections.append(
            "<p>No notebook source/text changes or non-image file diffs to display.</p>"
        )

    return _html_section("Working Tree Changes", "".join(sections))


def _format_rows(
    rows: list[tuple[str, str]],
    *,
    indent: str = "",
) -> list[str]:
    width = max(len(label) for label, _value in rows)
    rendered_lines: list[str] = []
    for label, value in rows:
        value_lines = str(value).splitlines() or [""]
        prefix = f"{indent}{label.ljust(width)} : "
        continuation_prefix = f"{indent}{' ' * width} : "
        rendered_lines.append(f"{prefix}{value_lines[0]}")
        rendered_lines.extend(
            f"{continuation_prefix}{line}" for line in value_lines[1:]
        )
    return rendered_lines


def _format_string_list(values: tuple[object, ...]) -> str:
    return ", ".join(str(value) for value in values) or "(none)"


def _format_optional_text(value: str | None) -> str:
    return value if value not in (None, "") else "(none)"


def _format_yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _notebook_diff_section(record: SnapshotRecord) -> str | None:
    relative_notebook_path = record.repo.relative_notebook_path
    if relative_notebook_path is None:
        return None
    if not str(relative_notebook_path).endswith(".ipynb"):
        return None

    notebook_diff = build_notebook_diff(
        notebook_path=record.notebook_context.notebook_path,
        relative_path=str(relative_notebook_path),
        repo_root=record.repo.repo_root,
        base_commit=record.diff_base_commit,
    )
    if notebook_diff is None:
        return None

    added_count = sum(1 for change in notebook_diff.changes if change.status == "added")
    removed_count = sum(
        1 for change in notebook_diff.changes if change.status == "removed"
    )
    changed_count = sum(
        1 for change in notebook_diff.changes if change.status == "changed"
    )
    summary_parts = [
        f"{changed_count} changed" if changed_count else "",
        f"{added_count} added" if added_count else "",
        f"{removed_count} removed" if removed_count else "",
    ]
    cell_summary = ", ".join(part for part in summary_parts if part != "") or "none"
    rendered_changes = "".join(
        _render_notebook_cell_change(change) for change in notebook_diff.changes
    )
    return "".join(
        [
            f"<p><strong>Notebook</strong>: {escape(notebook_diff.path)}</p>",
            f"<p>Cells: {escape(cell_summary)}</p>",
            rendered_changes,
        ]
    )


def _render_notebook_cell_change(change: NotebookCellChange) -> str:
    rows = [
        ("Cell", _html_text(_cell_position(change))),
        ("Status", _html_text(change.status.title())),
        ("Type", _html_text(_cell_type_label(change))),
    ]
    cell_id = _cell_id(change)
    if cell_id is not None:
        rows.append(("Cell ID", _html_text(cell_id)))

    content_sections = [_html_rows_table(rows)]
    old_cell = change.old_cell
    new_cell = change.new_cell
    if old_cell is not None or new_cell is not None:
        source_section = _render_diff_block(
            "Source",
            old_cell.source if old_cell is not None else "",
            new_cell.source if new_cell is not None else "",
        )
        if source_section != "":
            content_sections.append(source_section)

        output_section = _render_diff_block(
            "Outputs",
            old_cell.outputs if old_cell is not None else "",
            new_cell.outputs if new_cell is not None else "",
        )
        if output_section != "":
            content_sections.append(output_section)

    return "".join(content_sections)


def _render_diff_block(title: str, before: str, after: str) -> str:
    if before == after:
        return ""

    diff_lines = [
        line
        for line in difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
        if not line.startswith("---") and not line.startswith("+++")
    ]
    if not diff_lines:
        return ""

    return "".join(
        [f"<p><strong>{escape(title)}</strong></p>", _html_diff_pre(diff_lines)]
    )


def _html_diff_pre(lines: list[str] | tuple[str, ...]) -> str:
    rendered = "\n".join(_html_diff_line(line) for line in lines)
    return f"<pre>{rendered}</pre>"


def _html_diff_line(line: str) -> str:
    escaped_line = escape(line)
    if line.startswith("@@"):
        return f'<span style="color:#0b5394;font-weight:600;">{escaped_line}</span>'
    if line.startswith("+"):
        return f'<span style="color:#38761d;">{escaped_line}</span>'
    if line.startswith("-"):
        return f'<span style="color:#a61c00;">{escaped_line}</span>'
    return escaped_line


def _cell_position(change: NotebookCellChange) -> str:
    if change.old_index is not None and change.new_index is not None:
        old_position = f"Cell {change.old_index + 1}"
        new_position = f"Cell {change.new_index + 1}"
        if old_position == new_position:
            return new_position
        return f"{old_position} -> {new_position}"
    if change.new_index is not None:
        return f"Cell {change.new_index + 1}"
    if change.old_index is not None:
        return f"Cell {change.old_index + 1}"
    return "Cell"


def _cell_type_label(change: NotebookCellChange) -> str:
    old_type = change.old_cell.cell_type if change.old_cell is not None else None
    new_type = change.new_cell.cell_type if change.new_cell is not None else None
    if old_type is not None and new_type is not None:
        if old_type == new_type:
            return old_type
        return f"{old_type} -> {new_type}"
    return str(new_type or old_type or "unknown")


def _cell_id(change: NotebookCellChange) -> str | None:
    if change.new_cell is not None and change.new_cell.cell_id not in (None, ""):
        return change.new_cell.cell_id
    if change.old_cell is not None and change.old_cell.cell_id not in (None, ""):
        return change.old_cell.cell_id
    return None


def _parse_patch_sections(diff_text: str) -> tuple[_PatchSection, ...]:
    sections: list[_PatchSection] = []
    current_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_lines:
                section = _build_patch_section(current_lines)
                if section is not None:
                    sections.append(section)
            current_lines = [line]
            continue
        if current_lines:
            current_lines.append(line)
    if current_lines:
        section = _build_patch_section(current_lines)
        if section is not None:
            sections.append(section)
    return tuple(sections)


def _build_patch_section(lines: list[str]) -> _PatchSection | None:
    match = _DIFF_PATH_PATTERN.match(lines[0])
    if match is None:
        return None
    relative_path = match.group(2)
    status = "Changed"
    if any(line.startswith("new file mode ") for line in lines):
        status = "Added"
    elif any(line.startswith("deleted file mode ") for line in lines):
        status = "Removed"
    elif any(line.startswith("rename from ") for line in lines):
        status = "Renamed"

    return _PatchSection(
        relative_path=relative_path,
        status=status,
        display_lines=_display_patch_lines(lines),
    )


def _display_patch_lines(lines: list[str]) -> tuple[str, ...]:
    hunk_start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith(("@@", "Binary files "))
        ),
        None,
    )
    if hunk_start is not None:
        return tuple(lines[hunk_start:])

    content_start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith(("--- ", "rename from ", "Binary files "))
        ),
        1,
    )
    filtered_lines = [
        line
        for line in lines[content_start:]
        if not line.startswith("index ") and not line.startswith("new file mode ")
    ]
    return tuple(filtered_lines)


def _file_diff_section(section: _PatchSection) -> str:
    preformatted = (
        _html_diff_pre(section.display_lines)
        if section.display_lines
        else "<p>(no textual diff available)</p>"
    )
    return "".join(
        [
            f"<p><strong>File</strong>: {escape(section.relative_path)}</p>",
            _html_rows_table(
                [
                    ("Path", _html_text(section.relative_path)),
                    ("Status", _html_text(section.status)),
                ]
            ),
            preformatted,
        ]
    )


def _notebook_page_rich_text(
    record: SnapshotRecord,
    notebook_page: _NotebookPagePlan,
) -> str:
    notebook_model, load_error = _load_notebook_model(record, notebook_page.artifact)
    cells_section = (
        f"<p>{_html_text(load_error)}</p>"
        if load_error is not None
        else _render_notebook_cells(notebook_model)
    )
    diff_section = _notebook_diff_section(record)
    return "".join(
        [
            _html_section(
                "Notebook Snapshot",
                _html_rows_table(
                    [
                        ("Notebook", _html_text(notebook_page.display_name)),
                        ("Notebook path", _html_text(notebook_page.relative_path)),
                        ("Snapshot ID", _html_text(str(record.snapshot_id))),
                        ("Commit status", _html_text(_format_commit_status(record))),
                        (
                            "Attached figures",
                            _html_text(str(len(notebook_page.figures))),
                        ),
                    ]
                ),
            ),
            _html_section(
                "Notebook Diff",
                diff_section
                if diff_section is not None
                else "<p>No notebook source/text changes to display.</p>",
            ),
            _html_section("Notebook Cells", cells_section),
        ]
    )


def _render_notebook_cells(model: dict[str, object] | None) -> str:
    if model is None:
        return "<p>Notebook JSON is unavailable.</p>"
    cells = model.get("cells")
    if not isinstance(cells, list):
        return "<p>No notebook cells found.</p>"
    if cells == []:
        return "<p>No notebook cells found.</p>"

    rendered_cells: list[str] = []
    for index, raw_cell in enumerate(cells):
        cell = _object_dict(raw_cell)
        if cell is None:
            continue
        rendered_cells.append(_render_notebook_cell(index, cell))
    return (
        "".join(rendered_cells) if rendered_cells else "<p>No readable cells found.</p>"
    )


def _render_notebook_cell(index: int, cell: dict[str, object]) -> str:
    cell_type = _cell_value(cell.get("cell_type"), default="unknown")
    cell_id = _cell_value(cell.get("id"), default="(none)")
    execution_count = cell.get("execution_count")
    execution_label = (
        str(execution_count) if isinstance(execution_count, int) else "(none)"
    )
    source = _string_payload(cell.get("source")) or ""
    source_html = _python_code_pre(source) if cell_type == "code" else _html_pre(source)
    sections = [
        _html_section(
            f"Cell {index + 1}",
            _html_rows_table(
                [
                    ("Type", _html_text(cell_type)),
                    ("Cell ID", _html_text(cell_id)),
                    ("Execution count", _html_text(execution_label)),
                ]
            ),
        ),
        f"<p><strong>Source</strong></p>{source_html}",
    ]
    if cell_type == "code":
        sections.append(
            f"<p><strong>Outputs</strong></p>{_render_notebook_outputs(cell)}"
        )
    return "".join(sections)


def _render_notebook_outputs(cell: dict[str, object]) -> str:
    outputs = cell.get("outputs")
    if not isinstance(outputs, list) or outputs == []:
        return "<p>(no outputs)</p>"

    rendered_outputs: list[str] = []
    for index, raw_output in enumerate(outputs):
        output = _object_dict(raw_output)
        if output is None:
            continue
        output_type = _cell_value(output.get("output_type"), default="unknown")
        output_text = _notebook_output_text(output)
        rendered_outputs.append(
            "".join(
                [
                    _html_rows_table(
                        [
                            ("Output", _html_text(str(index + 1))),
                            ("Type", _html_text(output_type)),
                        ]
                    ),
                    _html_pre(output_text)
                    if output_text != ""
                    else "<p>(no readable output)</p>",
                ]
            )
        )
    if not rendered_outputs:
        return "<p>(no readable outputs)</p>"
    return "".join(rendered_outputs)


def _notebook_output_text(output: dict[str, object]) -> str:
    output_type = output.get("output_type")
    if output_type == "stream":
        return _string_payload(output.get("text")) or ""
    if output_type == "error":
        return _error_output_text(output)

    direct_text = _string_payload(output.get("text"))
    if direct_text is not None:
        return direct_text

    data = _object_dict(output.get("data"))
    if data is None:
        return ""
    text = _string_payload(data.get("text/plain"))
    if text is not None:
        return text
    image_mime_types = [name for name in sorted(data) if str(name).startswith("image/")]
    if image_mime_types:
        return "Image output: " + ", ".join(str(name) for name in image_mime_types)
    if data:
        return "Non-text output: " + ", ".join(str(name) for name in sorted(data))
    return ""


def _error_output_text(output: dict[str, object]) -> str:
    lines: list[str] = []
    error_name = output.get("ename")
    error_value = output.get("evalue")
    if isinstance(error_name, str) and error_name != "":
        if isinstance(error_value, str) and error_value != "":
            lines.append(f"{error_name}: {error_value}")
        else:
            lines.append(error_name)
    elif isinstance(error_value, str) and error_value != "":
        lines.append(error_value)

    traceback = _string_payload(output.get("traceback"))
    if traceback is not None and traceback != "":
        lines.append(traceback)
    return "\n".join(lines)


def _python_code_pre(source: str) -> str:
    try:
        rendered = _highlight_python(source)
    except (IndentationError, SyntaxError, tokenize.TokenError, UnicodeDecodeError):
        return _html_pre(source)
    return f'<pre style="white-space:pre-wrap;">{rendered}</pre>'


def _highlight_python(source: str) -> str:
    tokens = tokenize.generate_tokens(StringIO(source).readline)
    rendered: list[str] = []
    last_row = 1
    last_col = 0
    for token_info in tokens:
        token_type = token_info.type
        token_text = token_info.string
        if token_type == token.ENDMARKER:
            continue

        start_row, start_col = token_info.start
        end_row, end_col = token_info.end
        if start_row > last_row:
            rendered.append("\n" * (start_row - last_row))
            last_col = 0
        if start_col > last_col:
            rendered.append(" " * (start_col - last_col))
        rendered.append(_highlight_python_token(token_type, token_text))
        last_row = end_row
        last_col = end_col
    return "".join(rendered)


def _highlight_python_token(token_type: int, token_text: str) -> str:
    escaped = escape(token_text)
    if token_type == token.COMMENT:
        return _html_span(escaped, "color:#6a737d;font-style:italic;")
    if token_type == token.STRING:
        return _html_span(escaped, "color:#116329;")
    if token_type == token.NUMBER:
        return _html_span(escaped, "color:#8250df;")
    if token_type == token.NAME:
        if keyword.iskeyword(token_text):
            return _html_span(escaped, "color:#0b5394;font-weight:600;")
        if token_text in _PYTHON_BUILTINS:
            return _html_span(escaped, "color:#0f766e;")
    return escaped


def _html_span(content: str, style: str) -> str:
    return f'<span style="{style}">{content}</span>'


def _file_page_rich_text(
    record: SnapshotRecord,
    artifact: FileArtifact,
    payload: bytes,
) -> str:
    diff_section = _file_diff_sections_for_artifact(record, artifact)
    return "".join(
        [
            _html_section(
                "File Snapshot",
                _html_rows_table(
                    [
                        ("File", _html_text(artifact.display_name)),
                        (
                            "Relative path",
                            _html_text(_artifact_relative_path(artifact)),
                        ),
                        ("MIME type", _html_text(str(artifact.mime_type))),
                        ("Snapshot ID", _html_text(str(record.snapshot_id))),
                    ]
                ),
            ),
            _html_section(
                "File Diff",
                diff_section
                if diff_section != ""
                else "<p>No textual diff for this file.</p>",
            ),
            _html_section("Readable Preview", _file_preview_html(artifact, payload)),
        ]
    )


def _file_diff_sections_for_artifact(
    record: SnapshotRecord,
    artifact: FileArtifact,
) -> str:
    if record.dirty_diff is None or artifact.relative_path is None:
        return ""
    relative_path = str(artifact.relative_path)
    return "".join(
        _file_diff_section(section)
        for section in _parse_patch_sections(record.dirty_diff)
        if section.relative_path == relative_path
    )


def _file_preview_html(artifact: FileArtifact, payload: bytes) -> str:
    if _looks_binary(payload):
        return f"<p>Binary file preview is unavailable. Size: {len(payload)} bytes.</p>"

    preview_payload = payload[:_TEXT_PREVIEW_MAX_BYTES]
    decode_note = ""
    try:
        text = preview_payload.decode("utf-8")
    except UnicodeDecodeError:
        text = preview_payload.decode("utf-8", errors="replace")
        decode_note = "<p>Preview decoded as UTF-8 with replacement characters.</p>"

    truncation_note = ""
    if len(payload) > _TEXT_PREVIEW_MAX_BYTES:
        truncation_note = (
            "<p>Preview truncated to "
            f"{_TEXT_PREVIEW_MAX_BYTES} bytes from {len(payload)} bytes.</p>"
        )

    return "".join(
        [
            decode_note,
            truncation_note,
            _render_text_preview(
                text,
                suffix=Path(artifact.display_name).suffix.lower(),
                mime_type=str(artifact.mime_type),
            ),
        ]
    )


def _render_text_preview(text: str, *, suffix: str, mime_type: str) -> str:
    if suffix == ".py" or mime_type in {"text/x-python", "text/x-python-script"}:
        return _python_code_pre(text)
    if suffix == ".json" or mime_type == "application/json":
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return _html_pre(text)
        return _html_pre(json.dumps(loaded, indent=2, sort_keys=True))
    if suffix == ".csv" or mime_type == "text/csv":
        return _csv_preview_table(text, delimiter=",")
    if suffix == ".tsv" or mime_type == "text/tab-separated-values":
        return _csv_preview_table(text, delimiter="\t")
    return _html_pre(text)


def _csv_preview_table(text: str, *, delimiter: str) -> str:
    try:
        reader = csv.reader(StringIO(text), delimiter=delimiter)
        rows = [
            tuple(row[:_CSV_PREVIEW_MAX_COLUMNS])
            for row_index, row in enumerate(reader)
            if row_index < _CSV_PREVIEW_MAX_ROWS
        ]
    except csv.Error:
        return _html_pre(text)
    if not rows:
        return "<p>(empty file)</p>"

    rendered_rows = "".join(
        "<tr>" + "".join(f"<td>{_html_text(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    note = (
        "<p>CSV preview is capped at "
        f"{_CSV_PREVIEW_MAX_ROWS} rows and {_CSV_PREVIEW_MAX_COLUMNS} columns.</p>"
    )
    return f"{note}<table><tbody>{rendered_rows}</tbody></table>"


def _looks_binary(payload: bytes) -> bool:
    return b"\x00" in payload[:4096]


def _load_notebook_model(
    record: SnapshotRecord,
    artifact: NotebookArtifact | None,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        payload = (
            _notebook_bytes(artifact)
            if artifact is not None
            else Path(record.notebook_context.notebook_path).read_bytes()
        )
    except (OSError, LabArchivesWriteError) as exc:
        return None, f"Unable to read notebook file for preview: {exc}"

    try:
        loaded = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"Unable to parse notebook JSON for preview: {exc}"

    model = _object_dict(loaded)
    if model is None:
        return None, "Notebook JSON root is not an object."
    return model, None


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): nested_value for key, nested_value in value.items()}


def _string_payload(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [part for part in value if isinstance(part, str)]
        if len(parts) != len(value):
            return None
        return "".join(parts)
    return None


def _cell_value(value: object, *, default: str) -> str:
    if isinstance(value, str) and value != "":
        return value
    return default


def _is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES


def _notebook_artifacts(
    artifacts: tuple[ArtifactRef, ...],
) -> tuple[NotebookArtifact, ...]:
    return tuple(
        artifact for artifact in artifacts if isinstance(artifact, NotebookArtifact)
    )


def _figure_artifacts(artifacts: tuple[ArtifactRef, ...]) -> tuple[FigureArtifact, ...]:
    return tuple(
        artifact for artifact in artifacts if isinstance(artifact, FigureArtifact)
    )


def _file_artifacts(artifacts: tuple[ArtifactRef, ...]) -> tuple[FileArtifact, ...]:
    return tuple(
        sorted(
            (artifact for artifact in artifacts if isinstance(artifact, FileArtifact)),
            key=_file_page_label,
        )
    )


def _diff_artifacts(artifacts: tuple[ArtifactRef, ...]) -> tuple[DiffArtifact, ...]:
    return tuple(
        artifact for artifact in artifacts if isinstance(artifact, DiffArtifact)
    )


def _file_page_label(artifact: FileArtifact) -> str:
    if artifact.relative_path is not None:
        return str(artifact.relative_path)
    return artifact.display_name


def _artifact_page_name(
    artifact: ArtifactRef,
    artifact_pages: tuple[_ArtifactPageReference, ...],
) -> str:
    for artifact_page in artifact_pages:
        if artifact_page.artifact is artifact:
            return artifact_page.page_name
    return "(not attached)"


def _artifact_relative_path(artifact: ArtifactRef) -> str:
    if artifact.relative_path is None:
        return "(none)"
    return str(artifact.relative_path)


def _notebook_path(record: SnapshotRecord) -> str:
    notebook_path = (
        record.repo.relative_notebook_path or record.notebook_context.notebook_path
    )
    return str(notebook_path)


def _repository_name(record: SnapshotRecord) -> str:
    remote_url = record.repo.remote_url
    if remote_url is not None:
        normalized_remote = str(remote_url).strip().removesuffix(".git")
        if normalized_remote.startswith("git@"):
            host, _, repo_path = normalized_remote[4:].partition(":")
            if host and repo_path:
                return f"{host}/{repo_path}"
            return normalized_remote
        parsed_remote = urlparse(normalized_remote)
        host = parsed_remote.hostname or parsed_remote.netloc
        if host and parsed_remote.path:
            return f"{host}{parsed_remote.path}"
        return normalized_remote
    if record.repo.repo_root is not None:
        return Path(record.repo.repo_root).name or str(record.repo.repo_root)
    return "(no repository detected)"


def _working_tree_status(record: SnapshotRecord) -> str:
    if record.repo.repo_root is None:
        return "Not in a git repository"
    if record.repo.is_dirty and record.dirty_diff is not None:
        return "Dirty (diff included)"
    if record.repo.is_dirty:
        return "Dirty"
    if record.dirty_diff is not None:
        return "Clean after snapshot commit (diff included)"
    return "Clean"


def _format_commit_status(record: SnapshotRecord) -> str:
    if record.commit_hash is None:
        return "No commit requested or no repository detected"
    if record.commit_created:
        return "New snapshot commit created"
    return "Existing HEAD reused; no snapshot changes were staged"


def _format_commit_hash(commit_hash: str | None) -> str:
    if commit_hash is None:
        return "(none)"
    normalized = str(commit_hash)
    if len(normalized) <= 12:
        return normalized
    return f"{normalized[:12]} (full: {normalized})"


def _attachment_entry(artifact: ArtifactRef) -> object:
    payload, description = _attachment_content(artifact)
    return _attachment_entry_from_content(artifact, payload, description)


def _attachment_entry_from_content(
    artifact: ArtifactRef,
    payload: bytes,
    description: str,
) -> object:
    return labapi.Attachment(
        BytesIO(payload),
        str(artifact.mime_type),
        artifact.display_name,
        _describe_artifact(artifact, description),
    )


def _attachment_content(artifact: ArtifactRef) -> tuple[bytes, str]:
    match artifact:
        case FigureArtifact(
            bytes_payload=payload,
            figure_index=figure_index,
        ):
            return payload, f"Generated figure {figure_index}"
        case DiffArtifact(
            diff_text=diff_text,
        ):
            return diff_text.encode("utf-8"), _DIFF_DESCRIPTION
        case NotebookArtifact():
            return _notebook_bytes(artifact), _NOTEBOOK_DESCRIPTION
        case FileArtifact(
            bytes_payload=payload,
            local_path=local_path,
        ):
            if payload is None:
                payload = Path(local_path).read_bytes()
            return payload, _FILE_DESCRIPTION
        case _:
            raise LabArchivesWriteError(
                "Unsupported artifact type.",
                code="unsupported_artifact",
                context={"kind": str(artifact.kind)},
            )


def _notebook_bytes(artifact: NotebookArtifact) -> bytes:
    payload = artifact.bytes_payload
    if payload is None and artifact.local_path is not None:
        payload = Path(artifact.local_path).read_bytes()
    if payload is None:
        raise LabArchivesWriteError(
            "Notebook artifact has no payload.",
            code="missing_notebook_payload",
        )
    return payload


def _describe_artifact(artifact: ArtifactRef, description: str) -> str:
    if artifact.relative_path is None:
        return description
    return f"{description} ({artifact.relative_path})"

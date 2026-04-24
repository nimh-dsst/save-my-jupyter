from __future__ import annotations

import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Any

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
from save_my_jupyter.services.auth import LabArchivesSession

_NO_EXECUTION_SUMMARY = "(no execution summary available)"
_DIFF_DESCRIPTION = "Working tree diff"
_NOTEBOOK_DESCRIPTION = "Notebook snapshot"
_FILE_DESCRIPTION = "File artifact"


class LabArchivesAdapter:
    def write_snapshot(
        self,
        record: SnapshotRecord,
        session: LabArchivesSession,
    ) -> SnapshotPersistenceResult:
        try:
            page = _create_page(record, session)
            _populate_page(page, record)
        except Exception as exc:
            return SnapshotFailed(
                error_code="labarchives_write_failed",
                message=str(exc),
            )

        return SnapshotPersisted(
            snapshot_id=record.snapshot_id,
            labarchives_page_id=page.id,
        )


def _create_page(record: SnapshotRecord, session: LabArchivesSession) -> Any:
    directory = session.user.notebooks[str(record.labarchives_target.notebook_name)]
    for path_segment in render_root_path_template(
        str(record.labarchives_target.root_path),
        record,
    ):
        directory = directory.dir(path_segment)
    return directory.create(
        labapi.NotebookPage,
        record.timestamp.isoformat(timespec="seconds").replace(":", "-"),
        if_exists=labapi.InsertBehavior.Raise,
    )


def _populate_page(page: Any, record: SnapshotRecord) -> None:
    entries = page.entries
    for entry_type, content in _iter_entries(record):
        entries.create(entry_type, content)

    for attachment in _iter_attachments(record.artifacts):
        entries.create(labapi.AttachmentEntry, attachment)


def _iter_entries(record: SnapshotRecord) -> Iterator[tuple[type[object], str]]:
    yield labapi.TextEntry, _summary_html(record)
    yield (
        labapi.PlainTextEntry,
        json.dumps(
            _metadata(record),
            indent=2,
            sort_keys=True,
        ),
    )
    yield labapi.PlainTextEntry, _repo_summary(record)
    yield (
        labapi.PlainTextEntry,
        (record.produced_value_summary or _NO_EXECUTION_SUMMARY),
    )

    if record.dirty_diff is not None:
        yield labapi.PlainTextEntry, record.dirty_diff


def _summary_html(record: SnapshotRecord) -> str:
    return (
        f"<p><strong>Notebook:</strong> {record.notebook_context.notebook_name}</p>"
        f"<p><strong>Source:</strong> {record.source.value}</p>"
        f"<p><strong>Snapshot ID:</strong> {record.snapshot_id}</p>"
    )


def _metadata(record: SnapshotRecord) -> dict[str, object]:
    return {
        "commit_hash": record.commit_hash,
        "commit_url": record.commit_url,
        "dirty": record.dirty_diff is not None,
        "extension_version": record.extension_version,
        "metadata": {
            "experiment_context": record.metadata.experiment_context,
            "extra_fields": dict(record.metadata.extra_fields),
            "notes": record.metadata.notes,
            "run_label": record.metadata.run_label,
            "tags": list(record.metadata.tags),
        },
        "notebook_path": record.notebook_context.notebook_path,
        "path_rule_name": record.path_rule_name,
        "run_fingerprint": record.run_fingerprint,
        "trigger_cell_ids": list(record.trigger_cell_ids),
    }


def _repo_summary(record: SnapshotRecord) -> str:
    return "\n".join(
        [
            f"repo_root={record.repo.repo_root or '(none)'}",
            f"relative_notebook_path={record.repo.relative_notebook_path or '(none)'}",
            f"remote_url={record.repo.remote_url or '(none)'}",
            f"head_commit={record.repo.head_commit or '(none)'}",
            f"snapshot_commit={record.commit_hash or '(none)'}",
            f"commit_url={record.commit_url or '(none)'}",
        ]
    )


def _iter_attachments(artifacts: tuple[ArtifactRef, ...]) -> Iterator[object]:
    for artifact in artifacts:
        payload, description = _attachment_content(artifact)
        yield labapi.Attachment(
            BytesIO(payload),
            str(artifact.mime_type),
            artifact.display_name,
            description,
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

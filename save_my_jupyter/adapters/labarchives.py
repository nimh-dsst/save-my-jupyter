from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

from save_my_jupyter.domain import (
    ArtifactKind,
    ArtifactRef,
    DiffArtifact,
    FigureArtifact,
    FileArtifact,
    NotebookArtifact,
    SnapshotFailed,
    SnapshotPersisted,
    SnapshotRecord,
)
from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.labarchives import load_labapi
from save_my_jupyter.services.auth import LabArchivesSession


class LabArchivesAdapter:
    def write_snapshot(
        self,
        record: SnapshotRecord,
        session: LabArchivesSession,
    ) -> SnapshotPersisted | SnapshotFailed:
        try:
            labapi = load_labapi()
            notebook = session.user.notebooks[
                str(record.labarchives_target.notebook_name)
            ]
            scope_name = (
                record.path_rule_name
                or record.repo.relative_notebook_path
                or record.notebook_context.notebook_name
            )
            timestamp_name = record.timestamp.isoformat(timespec="seconds").replace(
                ":",
                "-",
            )
            target_root = notebook.dir(str(record.labarchives_target.root_path))
            snapshot_root = target_root.dir(str(record.user_id)).dir(str(scope_name))
            page = snapshot_root.create(
                labapi.NotebookPage,
                timestamp_name,
                if_exists=labapi.InsertBehavior.Raise,
            )
            self._write_summary_entries(labapi, page, record)
            self._upload_artifacts(labapi, page, record.artifacts)

            return SnapshotPersisted(
                snapshot_id=record.snapshot_id,
                labarchives_page_id=page.id,
            )
        except Exception as exc:
            return SnapshotFailed(
                error_code="labarchives_write_failed",
                message=str(exc),
            )

    def _write_summary_entries(
        self,
        labapi: Any,
        page: Any,
        record: SnapshotRecord,
    ) -> None:
        entries = page.entries
        entries.create(labapi.TextEntry, self._summary_entry(record))
        entries.create(
            labapi.PlainTextEntry,
            json.dumps(self._metadata_entry(record), indent=2, sort_keys=True),
        )
        entries.create(labapi.PlainTextEntry, self._git_info_entry(record))
        entries.create(
            labapi.PlainTextEntry,
            record.produced_value_summary or "(no execution summary available)",
        )
        if record.dirty_diff is not None:
            entries.create(labapi.PlainTextEntry, record.dirty_diff)

    def _upload_artifacts(
        self,
        labapi: Any,
        page: Any,
        artifacts: tuple[ArtifactRef, ...],
    ) -> None:
        for artifact in artifacts:
            attachment = self._to_attachment(labapi, artifact)
            page.entries.create(labapi.AttachmentEntry, attachment)

    def _summary_entry(self, record: SnapshotRecord) -> str:
        return (
            f"<p><strong>Notebook:</strong> {record.notebook_context.notebook_name}</p>"
            f"<p><strong>Source:</strong> {record.source.value}</p>"
            f"<p><strong>Snapshot ID:</strong> {record.snapshot_id}</p>"
        )

    def _metadata_entry(self, record: SnapshotRecord) -> dict[str, object]:
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

    def _git_info_entry(self, record: SnapshotRecord) -> str:
        return "\n".join(
            [
                f"repo_root={record.repo.repo_root or '(none)'}",
                "relative_notebook_path="
                f"{record.repo.relative_notebook_path or '(none)'}",
                f"remote_url={record.repo.remote_url or '(none)'}",
                f"repo_host={record.repo.repo_host.value}",
                f"head_commit={record.repo.head_commit or '(none)'}",
                f"snapshot_commit={record.commit_hash or '(none)'}",
                f"commit_url={record.commit_url or '(none)'}",
            ]
        )

    def _to_attachment(self, labapi: Any, artifact: object) -> object:
        if isinstance(artifact, FigureArtifact):
            return labapi.Attachment(
                BytesIO(artifact.bytes_payload),
                str(artifact.mime_type),
                artifact.display_name,
                f"Generated figure {artifact.figure_index}",
            )

        if isinstance(artifact, DiffArtifact):
            return labapi.Attachment(
                BytesIO(artifact.diff_text.encode("utf-8")),
                str(artifact.mime_type),
                artifact.display_name,
                "Working tree diff",
            )

        if isinstance(artifact, NotebookArtifact):
            payload = artifact.bytes_payload
            if payload is None and artifact.local_path is not None:
                payload = Path(artifact.local_path).read_bytes()
            if payload is None:
                raise LabArchivesWriteError(
                    "Notebook artifact has no payload.",
                    code="missing_notebook_payload",
                )
            return labapi.Attachment(
                BytesIO(payload),
                str(artifact.mime_type),
                artifact.display_name,
                "Notebook snapshot",
            )

        if isinstance(artifact, FileArtifact):
            payload = artifact.bytes_payload
            if payload is None:
                payload = Path(artifact.local_path).read_bytes()
            return labapi.Attachment(
                BytesIO(payload),
                str(artifact.mime_type),
                artifact.display_name,
                "File artifact",
            )

        raise LabArchivesWriteError(
            "Unsupported artifact type.",
            code="unsupported_artifact",
            context={"kind": str(getattr(artifact, "kind", ArtifactKind.FILE))},
        )

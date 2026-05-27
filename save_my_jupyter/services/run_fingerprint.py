from __future__ import annotations

from datetime import UTC
from hashlib import sha256

from save_my_jupyter.domain import (
    RunFingerprint,
    SnapshotRequest,
    SnapshotSource,
)
from save_my_jupyter.errors import RunFingerprintError


class RunFingerprintService:
    def compute(self, request: SnapshotRequest) -> RunFingerprint:
        notebook_path = str(request.notebook_context.notebook_path)
        document_id = str(request.notebook_context.document_id or "")
        kernel_id = str(request.notebook_context.kernel_id or "")
        match request.source:
            case SnapshotSource.MANUAL:
                timestamp = request.client_timestamp.astimezone(UTC)
                source_material = (
                    f"manual|{timestamp.isoformat(timespec='microseconds')}"
                )
            case SnapshotSource.TRIGGER_CELL:
                triggering_cell_id = str(
                    request.notebook_context.triggering_cell_id or ""
                )
                execution_count = (
                    str(request.notebook_context.cell_execution_count)
                    if request.notebook_context.cell_execution_count is not None
                    else ""
                )
                source_material = f"trigger|{triggering_cell_id}|{execution_count}"
        material = "|".join(
            [
                notebook_path,
                document_id,
                kernel_id,
                source_material,
            ]
        )
        if material == "|||":
            raise RunFingerprintError(
                "Insufficient request context for run fingerprint.",
                code="empty_run_fingerprint_material",
            )
        digest = sha256(material.encode("utf-8")).hexdigest()
        return RunFingerprint(digest)

    def same_run(self, left: SnapshotRequest, right: SnapshotRequest) -> bool:
        return self.compute(left) == self.compute(right)

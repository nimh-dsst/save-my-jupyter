from __future__ import annotations

from datetime import UTC
from hashlib import sha256

from save_my_jupyter.domain import RunFingerprint, SnapshotRequest, SnapshotSource
from save_my_jupyter.errors import RunFingerprintError


class RunFingerprintService:
    def compute(self, request: SnapshotRequest) -> RunFingerprint:
        timestamp = request.client_timestamp.astimezone(UTC)
        notebook_path = str(request.notebook_context.notebook_path)
        document_id = str(request.notebook_context.document_id or "")
        kernel_id = str(request.notebook_context.kernel_id or "")
        match request.source:
            case SnapshotSource.MANUAL:
                source_material = (
                    f"manual|{timestamp.isoformat(timespec='microseconds')}"
                )
            case SnapshotSource.TRIGGER_CELL:
                source_material = f"trigger|{int(timestamp.timestamp() // 5)}"
            case SnapshotSource.WATCHED_PATH:
                source_material = "|".join(
                    [
                        "watched_path",
                        str(request.watched_path_event.relative_path),
                        str(int(timestamp.timestamp() // 5)),
                    ]
                )
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

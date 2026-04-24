from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .enums import (
    ArtifactKind,
    CommitMode,
    SnapshotSource,
    TriggerMode,
)
from .models import (
    ArtifactRef,
    DiffArtifact,
    FigureArtifact,
    FileArtifact,
    ManualSnapshotRequest,
    NotebookArtifact,
    NotebookContext,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    SnapshotAccepted,
    SnapshotFailed,
    SnapshotPersisted,
    SnapshotPersistenceResult,
    SnapshotRecord,
    SnapshotRejected,
    SnapshotRequest,
    SnapshotSubmissionResult,
    TriggerCellSnapshotRequest,
    UserMetadata,
    WatchRegistrationRequest,
)
from .types import (
    CellId,
    CommitHash,
    DocumentId,
    KernelId,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    MimeType,
    NotebookPath,
    RelativeRepoPath,
    RelativeWatchPath,
    RemoteUrl,
    RepoRootPath,
    RunFingerprint,
    SnapshotId,
    UserId,
)

if TYPE_CHECKING:
    from save_my_jupyter.config.models import (
        EffectiveConfig,
        LabArchivesTarget,
        NotebookMetadataConfig,
        PathRuleConfig,
        RepoConfig,
        ResolvedPathRule,
        UserSettingsConfig,
    )

_CONFIG_EXPORTS = {
    "EffectiveConfig",
    "LabArchivesTarget",
    "NotebookMetadataConfig",
    "PathRuleConfig",
    "RepoConfig",
    "ResolvedPathRule",
    "UserSettingsConfig",
}

__all__ = [
    "ArtifactKind",
    "ArtifactRef",
    "CellId",
    "CommitHash",
    "CommitMode",
    "DiffArtifact",
    "DocumentId",
    "EffectiveConfig",
    "FigureArtifact",
    "FileArtifact",
    "KernelId",
    "LabArchivesNotebookName",
    "LabArchivesRootPath",
    "LabArchivesTarget",
    "ManualSnapshotRequest",
    "MimeType",
    "NotebookArtifact",
    "NotebookContext",
    "NotebookMetadataConfig",
    "NotebookPath",
    "PathRuleConfig",
    "RelativeRepoPath",
    "RelativeWatchPath",
    "RemoteUrl",
    "RepoConfig",
    "RepoRootPath",
    "ResolvedPathRule",
    "ResolvedRepoContext",
    "ResolvedSnapshotPlan",
    "RunFingerprint",
    "SnapshotAccepted",
    "SnapshotFailed",
    "SnapshotId",
    "SnapshotPersisted",
    "SnapshotPersistenceResult",
    "SnapshotRecord",
    "SnapshotRejected",
    "SnapshotRequest",
    "SnapshotSource",
    "SnapshotSubmissionResult",
    "TriggerCellSnapshotRequest",
    "TriggerMode",
    "UserId",
    "UserMetadata",
    "UserSettingsConfig",
    "WatchRegistrationRequest",
]


def __getattr__(name: str) -> Any:
    if name in _CONFIG_EXPORTS:
        from save_my_jupyter.config import models as config_models

        return getattr(config_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

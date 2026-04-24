from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .enums import (
    ArtifactKind,
    CommitMode,
    SnapshotSource,
    TriggerMode,
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
    StringMap,
    UserId,
)

type RelativeRepoPaths = tuple[RelativeRepoPath, ...]
type RelativeWatchPaths = tuple[RelativeWatchPath, ...]
type ArtifactRelativePath = RelativeRepoPath | RelativeWatchPath | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class UserMetadata:
    tags: tuple[str, ...] = ()
    notes: str | None = None
    run_label: str | None = None
    experiment_context: str | None = None
    extra_fields: StringMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookContext:
    notebook_path: NotebookPath
    notebook_name: str
    document_id: DocumentId | None = None
    kernel_id: KernelId | None = None
    cell_ids: tuple[CellId, ...] = ()
    triggering_cell_id: CellId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedRepoContext:
    repo_root: RepoRootPath | None
    relative_notebook_path: RelativeRepoPath | None
    remote_url: RemoteUrl | None
    head_commit: CommitHash | None
    is_dirty: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class LabArchivesTarget:
    notebook_name: LabArchivesNotebookName
    root_path: LabArchivesRootPath


@dataclass(frozen=True, slots=True, kw_only=True)
class _PathRuleBase:
    match_paths: RelativeRepoPaths
    watch_paths: RelativeWatchPaths = ()
    include_paths: RelativeWatchPaths = ()
    exclude_paths: RelativeWatchPaths = ()
    target: LabArchivesTarget | None = None
    metadata_template: StringMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class PathRuleConfig(_PathRuleBase):
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedPathRule(_PathRuleBase):
    rule_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookMetadataConfig:
    enabled: bool = True
    trigger_mode: TriggerMode = TriggerMode.MARKED_CELLS
    trigger_cell_ids: frozenset[CellId] = frozenset()
    watched_paths: RelativeWatchPaths = ()
    labarchives_target_notebook: LabArchivesNotebookName | None = None
    labarchives_target_root_path: LabArchivesRootPath | None = None
    default_metadata: StringMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSettingsConfig:
    default_commit_mode: CommitMode = CommitMode.PROMPT
    remember_commit_choice: bool = False
    default_tags: tuple[str, ...] = ()
    default_run_label: str | None = None
    default_experiment_context: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RepoConfig:
    project_name: str
    repo_root_strategy: Literal["git", "fixed"]
    default_all_cells_trigger: bool = False
    default_commit_mode: CommitMode = CommitMode.PROMPT
    default_watch_paths: RelativeWatchPaths = ()
    include_notebook_file: bool = True
    include_diff_when_dirty: bool = True
    default_target: LabArchivesTarget | None = None
    stage_notebook_on_commit: bool = True
    stage_watched_paths_on_commit: bool = False
    commit_message_template: str = "snapshot: {notebook_name} {timestamp}"
    path_rules: tuple[PathRuleConfig, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectiveConfig:
    all_cells_trigger: bool
    commit_mode: CommitMode
    watched_paths: RelativeWatchPaths
    include_notebook_file: bool
    include_diff_when_dirty: bool
    target: LabArchivesTarget
    metadata_template: StringMap
    stage_notebook_on_commit: bool
    stage_watched_paths_on_commit: bool
    commit_message_template: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _NotebookRequestBase:
    notebook_context: NotebookContext
    commit_mode: CommitMode
    user_metadata: UserMetadata


@dataclass(frozen=True, slots=True, kw_only=True)
class _SnapshotRequestBase(_NotebookRequestBase):
    client_timestamp: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualSnapshotRequest(_SnapshotRequestBase):
    source: Literal[SnapshotSource.MANUAL] = SnapshotSource.MANUAL


@dataclass(frozen=True, slots=True, kw_only=True)
class TriggerCellSnapshotRequest(_SnapshotRequestBase):
    source: Literal[SnapshotSource.TRIGGER_CELL] = SnapshotSource.TRIGGER_CELL


type SnapshotRequest = ManualSnapshotRequest | TriggerCellSnapshotRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class WatchRegistrationRequest(_NotebookRequestBase):
    watch_paths: RelativeWatchPaths


@dataclass(frozen=True, slots=True, kw_only=True)
class _ArtifactBase:
    display_name: str
    mime_type: MimeType


@dataclass(frozen=True, slots=True, kw_only=True)
class _StoredArtifact(_ArtifactBase):
    local_path: Path | None = None
    relative_path: ArtifactRelativePath = None
    bytes_payload: bytes | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookArtifact(_StoredArtifact):
    relative_path: RelativeRepoPath | None = None
    kind: Literal[ArtifactKind.NOTEBOOK] = ArtifactKind.NOTEBOOK


@dataclass(frozen=True, slots=True, kw_only=True)
class FigureArtifact(_StoredArtifact):
    figure_index: int
    bytes_payload: bytes
    relative_path: RelativeRepoPath | None = None
    kind: Literal[ArtifactKind.FIGURE] = ArtifactKind.FIGURE


@dataclass(frozen=True, slots=True, kw_only=True)
class FileArtifact(_StoredArtifact):
    local_path: Path
    relative_path: ArtifactRelativePath = None
    kind: Literal[ArtifactKind.FILE] = ArtifactKind.FILE


@dataclass(frozen=True, slots=True, kw_only=True)
class DiffArtifact(_StoredArtifact):
    diff_text: str
    relative_path: RelativeRepoPath | None = None
    kind: Literal[ArtifactKind.DIFF] = ArtifactKind.DIFF


type ArtifactRef = NotebookArtifact | FigureArtifact | FileArtifact | DiffArtifact


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedSnapshotPlan:
    request: SnapshotRequest
    repo: ResolvedRepoContext
    path_rule: ResolvedPathRule | None
    effective_config: EffectiveConfig
    run_fingerprint: RunFingerprint


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotRecord:
    snapshot_id: SnapshotId
    timestamp: datetime
    source: SnapshotSource
    user_id: UserId
    notebook_context: NotebookContext
    repo: ResolvedRepoContext
    path_rule_name: str | None
    commit_hash: CommitHash | None
    commit_url: str | None
    dirty_diff: str | None
    run_fingerprint: RunFingerprint
    trigger_cell_ids: tuple[CellId, ...]
    executed_cell_ids: tuple[CellId, ...]
    produced_value_summary: str | None
    artifacts: tuple[ArtifactRef, ...]
    metadata: UserMetadata
    labarchives_target: LabArchivesTarget
    extension_version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotAccepted:
    job_id: str
    queue_position: int
    status: Literal["accepted"] = "accepted"


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotRejected:
    reason_code: str
    message: str
    status: Literal["rejected"] = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotPersisted:
    snapshot_id: SnapshotId
    labarchives_page_id: str
    status: Literal["persisted"] = "persisted"


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotFailed:
    error_code: str
    message: str
    status: Literal["failed"] = "failed"


type SnapshotSubmissionResult = SnapshotAccepted | SnapshotRejected
type SnapshotPersistenceResult = SnapshotPersisted | SnapshotFailed

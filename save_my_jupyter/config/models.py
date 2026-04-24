from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from save_my_jupyter.domain.enums import CommitMode, TriggerMode
from save_my_jupyter.domain.types import (
    CellId,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    RelativeRepoPath,
    RelativeWatchPath,
    StringMap,
)

type RelativeRepoPaths = tuple[RelativeRepoPath, ...]
type RelativeWatchPaths = tuple[RelativeWatchPath, ...]


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


@dataclass(frozen=True, slots=True)
class RepoConfigBootstrapResult:
    config_path: Path
    root_directory: Path
    status: Literal["created", "exists"]


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    repo_config: RepoConfig | None
    notebook_metadata: NotebookMetadataConfig
    user_settings: UserSettingsConfig
    path_rule: ResolvedPathRule | None
    effective_config: EffectiveConfig

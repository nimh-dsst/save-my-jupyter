from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from save_my_jupyter.domain.enums import CommitMode, TriggerMode
from save_my_jupyter.domain.provenance import ConfigLayer
from save_my_jupyter.domain.types import (
    CellId,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    RelativeWatchPath,
    StringMap,
)

type RelativeWatchPaths = tuple[RelativeWatchPath, ...]

# The inferred default LabArchives destination scopes by the authenticated user's
# email because shared notebooks are the norm here (contract C-DEST-06). The
# `{...}` parts are path-template variables rendered at snapshot time.
INFERRED_TARGET_NOTEBOOK = LabArchivesNotebookName("Jupyter Snapshots")
INFERRED_TARGET_ROOT_PATH = LabArchivesRootPath(
    "Notebook Log/{user_email}/{project_name}/{relative_notebook_path}"
)
DEFAULT_PROJECT_NAME = "save-my-jupyter"
DEFAULT_COMMIT_MESSAGE_TEMPLATE = "snapshot: {notebook_name} {timestamp}"


@dataclass(frozen=True, slots=True, kw_only=True)
class LabArchivesTarget:
    notebook_name: LabArchivesNotebookName
    root_path: LabArchivesRootPath
    project_name: str = DEFAULT_PROJECT_NAME


@dataclass(frozen=True, slots=True, kw_only=True)
class RepoConfig:
    """Parsed `.save-my-jupyter.toml` (contract C-CONFIG-04). Optional fields
    are `None` when the file did not set them, so provenance stays exact."""

    project_name: str
    repo_root_strategy: Literal["git", "fixed"] = "git"
    default_all_cells_trigger: bool | None = None
    default_commit_mode: CommitMode | None = None
    default_tags: tuple[str, ...] = ()
    default_watch_paths: RelativeWatchPaths | None = None
    include_notebook_file: bool | None = None
    include_diff_when_dirty: bool | None = None
    default_target_notebook: LabArchivesNotebookName | None = None
    default_target_root_path: LabArchivesRootPath | None = None
    stage_notebook_on_commit: bool | None = None
    stage_watched_paths_on_commit: bool | None = None
    commit_message_template: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NotebookMetadataConfig:
    """Parsed `notebook.metadata.save_my_jupyter` (contract C-CONFIG-05)."""

    enabled: bool = True
    trigger_mode: TriggerMode = TriggerMode.MARKED_CELLS
    trigger_cell_ids: frozenset[CellId] = frozenset()
    watched_paths: RelativeWatchPaths = ()
    labarchives_target_notebook: LabArchivesNotebookName | None = None
    labarchives_target_root_path: LabArchivesRootPath | None = None
    default_metadata: StringMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSettingsConfig:
    """Parsed JupyterLab user preferences (contract C-CONFIG-07). An unset
    `default_commit_mode` (None) leaves the effective mode at `ask`."""

    default_commit_mode: CommitMode | None = None
    remember_commit_choice: bool = False
    default_tags: tuple[str, ...] = ()
    default_run_label: str | None = None


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
class ResolvedConfig:
    """The merged effective config plus per-field provenance, so the panel can
    label `(inferred)` values inline (contracts C-CONFIG-02, C-CONFIG-11).

    Provenance keys: ``commit_mode``, ``all_cells_trigger``, ``watched_paths``,
    ``include_notebook_file``, ``include_diff_when_dirty``, ``target_notebook``,
    ``target_root_path``, ``project_name``, ``metadata_template``,
    ``stage_notebook_on_commit``, ``stage_watched_paths_on_commit``,
    ``commit_message_template``.
    """

    effective: EffectiveConfig
    provenance: Mapping[str, ConfigLayer]

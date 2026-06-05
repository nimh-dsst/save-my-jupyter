"""Five-layer config resolution (target CONFIGURE). Pure: every input is an
already-parsed typed config layer, and the output is the effective config plus
per-field provenance so the panel can label inferred values inline.

Precedence (contract C-CONFIG-01): request > notebook > user > repo > inferred >
hardcoded fallback. A layer that did not set a field leaves it `None`, so the
winning layer recorded in provenance is exact rather than guessed."""

from __future__ import annotations

from typing import TypeVar

from save_my_jupyter.domain.config import (
    DEFAULT_COMMIT_MESSAGE_TEMPLATE,
    DEFAULT_PROJECT_NAME,
    INFERRED_TARGET_NOTEBOOK,
    INFERRED_TARGET_ROOT_PATH,
    EffectiveConfig,
    LabArchivesTarget,
    NotebookMetadataConfig,
    RelativeWatchPaths,
    RepoConfig,
    ResolvedConfig,
    UserSettingsConfig,
)
from save_my_jupyter.domain.enums import CommitMode, TriggerMode
from save_my_jupyter.domain.provenance import ConfigLayer
from save_my_jupyter.domain.types import StringMap

_EMPTY_WATCH_PATHS: RelativeWatchPaths = ()
_EMPTY_METADATA: StringMap = {}
_T = TypeVar("_T")


def _first(*candidates: tuple[_T | None, ConfigLayer]) -> tuple[_T, ConfigLayer]:
    """Return the first candidate whose value is set, with its layer. The final
    candidate must be a guaranteed (non-None) default, so this never falls off."""
    for value, layer in candidates:
        if value is not None:
            return value, layer
    raise AssertionError("config resolution requires a guaranteed default candidate")


def resolve_effective_config(
    *,
    request_commit_mode: CommitMode | None = None,
    request_watched_paths: RelativeWatchPaths | None = None,
    notebook: NotebookMetadataConfig,
    user: UserSettingsConfig,
    repo: RepoConfig | None,
) -> ResolvedConfig:
    provenance: dict[str, ConfigLayer] = {}

    commit_mode, provenance["commit_mode"] = _first(
        (request_commit_mode, ConfigLayer.REQUEST),
        (user.default_commit_mode, ConfigLayer.USER),
        (repo.default_commit_mode if repo else None, ConfigLayer.REPO),
        (CommitMode.ASK, ConfigLayer.FALLBACK),
    )

    # all-cells trigger can only be turned *on* by a higher layer (legacy OR
    # semantics): notebook trigger_mode, else repo default, else off.
    notebook_all_cells = notebook.trigger_mode is TriggerMode.ALL_CELLS or None
    repo_all_cells = bool(repo and repo.default_all_cells_trigger) or None
    all_cells_trigger, provenance["all_cells_trigger"] = _first(
        (notebook_all_cells, ConfigLayer.NOTEBOOK),
        (repo_all_cells, ConfigLayer.REPO),
        (False, ConfigLayer.FALLBACK),
    )

    # A missing request falls through; an explicit empty request clears lower layers.
    watched_paths, provenance["watched_paths"] = _first(
        (request_watched_paths, ConfigLayer.REQUEST),
        (notebook.watched_paths or None, ConfigLayer.NOTEBOOK),
        ((repo.default_watch_paths if repo else None) or None, ConfigLayer.REPO),
        (_EMPTY_WATCH_PATHS, ConfigLayer.FALLBACK),
    )

    include_notebook_file, provenance["include_notebook_file"] = _first(
        (repo.include_notebook_file if repo else None, ConfigLayer.REPO),
        (True, ConfigLayer.FALLBACK),
    )
    include_diff_when_dirty, provenance["include_diff_when_dirty"] = _first(
        (repo.include_diff_when_dirty if repo else None, ConfigLayer.REPO),
        (True, ConfigLayer.FALLBACK),
    )

    target_notebook, provenance["target_notebook"] = _first(
        (notebook.labarchives_target_notebook, ConfigLayer.NOTEBOOK),
        (repo.default_target_notebook if repo else None, ConfigLayer.REPO),
        (INFERRED_TARGET_NOTEBOOK, ConfigLayer.INFERRED),
    )
    target_root_path, provenance["target_root_path"] = _first(
        (notebook.labarchives_target_root_path, ConfigLayer.NOTEBOOK),
        (repo.default_target_root_path if repo else None, ConfigLayer.REPO),
        (INFERRED_TARGET_ROOT_PATH, ConfigLayer.INFERRED),
    )
    project_name, provenance["project_name"] = _first(
        (repo.project_name if repo else None, ConfigLayer.REPO),
        (DEFAULT_PROJECT_NAME, ConfigLayer.FALLBACK),
    )

    repo_metadata = repo.default_metadata if repo else {}
    metadata_template: StringMap = {**repo_metadata, **notebook.default_metadata}
    if notebook.default_metadata:
        provenance["metadata_template"] = ConfigLayer.NOTEBOOK
    elif repo_metadata:
        provenance["metadata_template"] = ConfigLayer.REPO
    else:
        metadata_template = _EMPTY_METADATA
        provenance["metadata_template"] = ConfigLayer.FALLBACK

    stage_notebook_on_commit, provenance["stage_notebook_on_commit"] = _first(
        (repo.stage_notebook_on_commit if repo else None, ConfigLayer.REPO),
        (True, ConfigLayer.FALLBACK),
    )
    stage_watched, provenance["stage_watched_paths_on_commit"] = _first(
        (repo.stage_watched_paths_on_commit if repo else None, ConfigLayer.REPO),
        (True, ConfigLayer.FALLBACK),
    )
    commit_message_template, provenance["commit_message_template"] = _first(
        (repo.commit_message_template if repo else None, ConfigLayer.REPO),
        (DEFAULT_COMMIT_MESSAGE_TEMPLATE, ConfigLayer.FALLBACK),
    )

    effective = EffectiveConfig(
        all_cells_trigger=all_cells_trigger,
        commit_mode=commit_mode,
        watched_paths=watched_paths,
        include_notebook_file=include_notebook_file,
        include_diff_when_dirty=include_diff_when_dirty,
        target=LabArchivesTarget(
            notebook_name=target_notebook,
            root_path=target_root_path,
            project_name=project_name,
        ),
        metadata_template=metadata_template,
        stage_notebook_on_commit=stage_notebook_on_commit,
        stage_watched_paths_on_commit=stage_watched,
        commit_message_template=commit_message_template,
    )
    return ResolvedConfig(effective=effective, provenance=provenance)

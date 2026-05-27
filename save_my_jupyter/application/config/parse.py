"""Pure parsers for the three config sources the resolver merges (target
CONFIGURE, contracts C-CONFIG-04/05/07). Each turns an external shape (TOML
text, notebook metadata, settings registry) into a typed config layer. Wrong-
typed values fall through to higher layers rather than raising; only an
unparseable TOML file and an unknown repo_root_strategy are hard errors."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from typing import Literal, cast

from save_my_jupyter.application.snapshot.guards import validate_watched_path
from save_my_jupyter.domain.config import (
    NotebookMetadataConfig,
    RelativeWatchPaths,
    RepoConfig,
    UserSettingsConfig,
)
from save_my_jupyter.domain.enums import CommitMode, TriggerMode
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.guards import WatchedPathRejected
from save_my_jupyter.domain.types import (
    CellId,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    RelativeWatchPath,
    StringMap,
)


def parse_repo_config(toml_text: str, *, default_project_name: str) -> RepoConfig:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise SnapshotError(
            "Could not parse .save-my-jupyter.toml.",
            code="repo_config_parse_failed",
            context={"error": str(exc)},
        ) from exc

    project = _section(data, "project")
    defaults = _section(data, "defaults")
    labarchives = _section(data, "labarchives")
    git = _section(data, "git")

    raw_strategy = _opt_str(project, "repo_root_strategy")
    strategy: Literal["git", "fixed"]
    if raw_strategy in (None, "git"):
        strategy = "git"
    elif raw_strategy == "fixed":
        strategy = "fixed"
    else:
        raise SnapshotError(
            "repo_root_strategy must be 'git' or 'fixed'.",
            code="invalid_repo_root_strategy",
            context={"value": raw_strategy},
        )

    notebook = _opt_str(labarchives, "target_notebook")
    root_path = _opt_str(labarchives, "target_root_path")
    return RepoConfig(
        project_name=_opt_str(project, "name") or default_project_name,
        repo_root_strategy=strategy,
        default_all_cells_trigger=_opt_bool(defaults, "all_cells_trigger"),
        default_commit_mode=_opt_commit_mode(defaults, "commit_mode"),
        default_tags=tuple(_str_list(defaults, "default_tags")),
        default_watch_paths=_opt_watch_paths(defaults, "watch_paths"),
        include_notebook_file=_opt_bool(defaults, "include_notebook_file"),
        include_diff_when_dirty=_opt_bool(defaults, "include_diff_when_dirty"),
        default_target_notebook=(
            LabArchivesNotebookName(notebook) if notebook is not None else None
        ),
        default_target_root_path=(
            LabArchivesRootPath(root_path) if root_path is not None else None
        ),
        stage_notebook_on_commit=_opt_bool(git, "stage_notebook_on_commit"),
        stage_watched_paths_on_commit=_opt_bool(git, "stage_watched_paths_on_commit"),
        commit_message_template=_opt_str(git, "commit_message_template"),
    )


def parse_notebook_metadata(metadata: Mapping[str, object]) -> NotebookMetadataConfig:
    notebook = _opt_str(metadata, "labarchives_target_notebook")
    root_path = _opt_str(metadata, "labarchives_target_root_path")
    all_cells = _bool(metadata, "all_cells_trigger", default=False)
    return NotebookMetadataConfig(
        enabled=_bool(metadata, "enabled", default=True),
        trigger_mode=TriggerMode.ALL_CELLS if all_cells else TriggerMode.MARKED_CELLS,
        trigger_cell_ids=frozenset(
            CellId(value) for value in _str_list(metadata, "trigger_cell_ids")
        ),
        watched_paths=_metadata_watch_paths(metadata, "watched_paths"),
        labarchives_target_notebook=(
            LabArchivesNotebookName(notebook) if notebook is not None else None
        ),
        labarchives_target_root_path=(
            LabArchivesRootPath(root_path) if root_path is not None else None
        ),
        default_metadata=_str_map(metadata, "default_metadata"),
    )


def parse_user_settings(settings: Mapping[str, object]) -> UserSettingsConfig:
    return UserSettingsConfig(
        default_commit_mode=_opt_commit_mode(settings, "defaultCommitMode"),
        remember_commit_choice=_bool(settings, "rememberCommitChoice", default=False),
        default_tags=tuple(_str_list(settings, "defaultTags")),
        default_run_label=_opt_str(settings, "defaultRunLabel"),
    )


def _section(data: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = data.get(name)
    if isinstance(value, Mapping):
        return cast("Mapping[str, object]", value)
    return {}


def _opt_str(section: Mapping[str, object], key: str) -> str | None:
    value = section.get(key)
    return value if isinstance(value, str) else None


def _opt_bool(section: Mapping[str, object], key: str) -> bool | None:
    value = section.get(key)
    return value if isinstance(value, bool) else None


def _bool(section: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = section.get(key)
    return value if isinstance(value, bool) else default


def _opt_commit_mode(section: Mapping[str, object], key: str) -> CommitMode | None:
    value = _opt_str(section, key)
    if value is None:
        return None
    if value == "prompt":
        return CommitMode.ASK
    try:
        return CommitMode(value)
    except ValueError:
        return None


def _opt_watch_paths(
    section: Mapping[str, object], key: str
) -> RelativeWatchPaths | None:
    paths: list[RelativeWatchPath] = []
    for value in _str_list(section, key):
        normalized = _normalize_watch_path(value, strict=True)
        assert normalized is not None
        paths.append(RelativeWatchPath(normalized))
    return tuple(paths) or None


def _metadata_watch_paths(
    section: Mapping[str, object], key: str
) -> RelativeWatchPaths:
    paths: list[RelativeWatchPath] = []
    for value in _str_list(section, key):
        normalized = _normalize_watch_path(value, strict=False)
        if normalized is not None:
            paths.append(RelativeWatchPath(normalized))
    return tuple(paths)


def _normalize_watch_path(raw: str, *, strict: bool) -> str | None:
    validation = validate_watched_path(raw)
    if not isinstance(validation, WatchedPathRejected):
        return validation.normalized
    if strict:
        raise SnapshotError(
            validation.message, code=validation.code, context={"path": raw}
        )
    return None


def _str_list(section: Mapping[str, object], key: str) -> list[str]:
    value = section.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _str_map(section: Mapping[str, object], key: str) -> StringMap:
    value = section.get(key)
    if not isinstance(value, Mapping):
        return {}
    return {str(name): item for name, item in value.items() if isinstance(item, str)}

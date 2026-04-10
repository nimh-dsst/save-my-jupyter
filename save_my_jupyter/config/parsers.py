from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from save_my_jupyter.domain import (
    CellId,
    CommitMode,
    EffectiveConfig,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    LabArchivesTarget,
    NotebookMetadataConfig,
    PathRuleConfig,
    RelativeRepoPath,
    RelativeWatchPath,
    RepoConfig,
    TriggerMode,
    UserSettingsConfig,
)
from save_my_jupyter.errors import ConfigParseError, ConfigValidationError
from save_my_jupyter.parsing import (
    normalize_relative_path_text,
    optional_mapping,
    optional_str,
    require_bool,
    require_mapping,
    require_str,
    str_tuple,
)


def parse_repo_config_file(path: Path) -> RepoConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigParseError(
            f"Unable to parse repo config at {path}.",
            code="repo_config_parse_failed",
            context={"path": str(path)},
        ) from exc

    return parse_repo_config(require_mapping(raw, field_name="repo_config"))


def parse_repo_config(raw: Mapping[str, object]) -> RepoConfig:
    project = optional_mapping(raw.get("project"), field_name="project") or {}
    defaults = optional_mapping(raw.get("defaults"), field_name="defaults") or {}
    labarchives = (
        optional_mapping(raw.get("labarchives"), field_name="labarchives") or {}
    )
    git = optional_mapping(raw.get("git"), field_name="git") or {}

    project_name = require_str(
        project.get("name", "save-my-jupyter"),
        field_name="project.name",
    )
    repo_root_strategy = require_str(
        project.get("repo_root_strategy", "git"),
        field_name="project.repo_root_strategy",
    )
    if repo_root_strategy not in {"git", "fixed"}:
        raise ConfigValidationError(
            "repo_root_strategy must be either 'git' or 'fixed'.",
            code="invalid_repo_root_strategy",
        )

    path_rules_raw = raw.get("path_rule", ())
    if not isinstance(path_rules_raw, tuple | list):
        raise ConfigValidationError(
            "path_rule entries must be a list of tables.",
            code="invalid_path_rules",
        )

    path_rules = tuple(
        parse_path_rule(require_mapping(item, field_name="path_rule"))
        for item in path_rules_raw
    )
    _validate_path_rule_names(path_rules)

    return RepoConfig(
        project_name=project_name,
        repo_root_strategy=cast("Literal['git', 'fixed']", repo_root_strategy),
        default_all_cells_trigger=require_bool(
            defaults.get("all_cells_trigger", False),
            field_name="defaults.all_cells_trigger",
        ),
        default_commit_mode=CommitMode(
            require_str(
                defaults.get("commit_mode", CommitMode.PROMPT.value),
                field_name="defaults.commit_mode",
            )
        ),
        default_watch_paths=tuple(
            RelativeWatchPath(normalize_relative_path_text(path))
            for path in str_tuple(
                defaults.get("watch_paths"),
                field_name="defaults.watch_paths",
            )
        ),
        include_notebook_file=require_bool(
            defaults.get("include_notebook_file", True),
            field_name="defaults.include_notebook_file",
        ),
        include_diff_when_dirty=require_bool(
            defaults.get("include_diff_when_dirty", True),
            field_name="defaults.include_diff_when_dirty",
        ),
        default_target=_parse_target(
            notebook_name=optional_str(
                labarchives.get("target_notebook"),
                field_name="labarchives.target_notebook",
            ),
            root_path=optional_str(
                labarchives.get("target_root_path"),
                field_name="labarchives.target_root_path",
            ),
        ),
        stage_notebook_on_commit=require_bool(
            git.get("stage_notebook_on_commit", True),
            field_name="git.stage_notebook_on_commit",
        ),
        stage_watched_paths_on_commit=require_bool(
            git.get("stage_watched_paths_on_commit", False),
            field_name="git.stage_watched_paths_on_commit",
        ),
        commit_message_template=require_str(
            git.get("commit_message_template", "snapshot: {notebook_name} {timestamp}"),
            field_name="git.commit_message_template",
        ),
        path_rules=path_rules,
    )


def parse_path_rule(raw: Mapping[str, object]) -> PathRuleConfig:
    return PathRuleConfig(
        name=require_str(raw.get("name"), field_name="path_rule.name"),
        match_paths=tuple(
            RelativeRepoPath(normalize_relative_path_text(path))
            for path in str_tuple(
                raw.get("match_paths"),
                field_name="path_rule.match_paths",
            )
        ),
        watch_paths=tuple(
            RelativeWatchPath(normalize_relative_path_text(path))
            for path in str_tuple(
                raw.get("watch_paths"),
                field_name="path_rule.watch_paths",
            )
        ),
        include_paths=tuple(
            RelativeWatchPath(normalize_relative_path_text(path))
            for path in str_tuple(
                raw.get("include_paths"),
                field_name="path_rule.include_paths",
            )
        ),
        exclude_paths=tuple(
            RelativeWatchPath(normalize_relative_path_text(path))
            for path in str_tuple(
                raw.get("exclude_paths"),
                field_name="path_rule.exclude_paths",
            )
        ),
        target=_parse_target(
            notebook_name=optional_str(
                raw.get("labarchives_target_notebook"),
                field_name="path_rule.labarchives_target_notebook",
            ),
            root_path=optional_str(
                raw.get("labarchives_target_root_path"),
                field_name="path_rule.labarchives_target_root_path",
            ),
        ),
        metadata_template=_parse_string_mapping(
            optional_mapping(
                raw.get("metadata_template"),
                field_name="path_rule.metadata_template",
            )
            or {}
        ),
    )


def parse_user_settings(raw: Mapping[str, object]) -> UserSettingsConfig:
    return UserSettingsConfig(
        default_commit_mode=CommitMode(
            require_str(
                raw.get("defaultCommitMode", CommitMode.PROMPT.value),
                field_name="defaultCommitMode",
            )
        ),
        remember_commit_choice=require_bool(
            raw.get("rememberCommitChoice", False),
            field_name="rememberCommitChoice",
        ),
        default_tags=str_tuple(raw.get("defaultTags"), field_name="defaultTags"),
        default_run_label=optional_str(
            raw.get("defaultRunLabel"),
            field_name="defaultRunLabel",
        ),
        default_experiment_context=optional_str(
            raw.get("defaultExperimentContext"),
            field_name="defaultExperimentContext",
        ),
    )


def parse_notebook_metadata(raw: Mapping[str, object]) -> NotebookMetadataConfig:
    return NotebookMetadataConfig(
        enabled=require_bool(raw.get("enabled", True), field_name="enabled"),
        trigger_mode=TriggerMode.ALL_CELLS
        if require_bool(
            raw.get("all_cells_trigger", False),
            field_name="all_cells_trigger",
        )
        else TriggerMode.MARKED_CELLS,
        trigger_cell_ids=frozenset(
            CellId(cell_id)
            for cell_id in str_tuple(
                raw.get("trigger_cell_ids"),
                field_name="trigger_cell_ids",
            )
        ),
        watched_paths=tuple(
            RelativeWatchPath(normalize_relative_path_text(path))
            for path in str_tuple(raw.get("watched_paths"), field_name="watched_paths")
        ),
        labarchives_target_notebook=_parse_notebook_name(
            optional_str(
                raw.get("labarchives_target_notebook"),
                field_name="labarchives_target_notebook",
            )
        ),
        labarchives_target_root_path=_parse_root_path(
            optional_str(
                raw.get("labarchives_target_root_path"),
                field_name="labarchives_target_root_path",
            )
        ),
        default_metadata=_parse_string_mapping(
            optional_mapping(raw.get("default_metadata"), field_name="default_metadata")
            or {}
        ),
    )


def merge_effective_config(
    *,
    repo_config: RepoConfig | None,
    notebook_metadata: NotebookMetadataConfig,
    user_settings: UserSettingsConfig,
    path_rule: PathRuleConfig | None,
    request_commit_mode: CommitMode,
) -> EffectiveConfig:
    path_rule_target = (
        path_rule.target
        if path_rule is not None and path_rule.target is not None
        else None
    )
    repo_target = repo_config.default_target if repo_config is not None else None
    target_notebook_name = (
        notebook_metadata.labarchives_target_notebook
        or (path_rule_target.notebook_name if path_rule_target is not None else None)
        or (repo_target.notebook_name if repo_target is not None else None)
        or LabArchivesNotebookName("Jupyter Snapshots")
    )
    target_root_path = (
        notebook_metadata.labarchives_target_root_path
        or (path_rule_target.root_path if path_rule_target is not None else None)
        or (repo_target.root_path if repo_target is not None else None)
        or LabArchivesRootPath("Notebook Log")
    )
    metadata_template = (
        notebook_metadata.default_metadata
        if notebook_metadata.default_metadata
        else (
            path_rule.metadata_template
            if path_rule is not None and path_rule.metadata_template
            else {}
        )
    )
    effective_commit_mode = request_commit_mode
    if effective_commit_mode is CommitMode.PROMPT:
        effective_commit_mode = user_settings.default_commit_mode
    if effective_commit_mode is CommitMode.PROMPT and repo_config is not None:
        effective_commit_mode = repo_config.default_commit_mode

    return EffectiveConfig(
        all_cells_trigger=notebook_metadata.trigger_mode is TriggerMode.ALL_CELLS
        or (
            repo_config.default_all_cells_trigger if repo_config is not None else False
        ),
        commit_mode=effective_commit_mode,
        watched_paths=notebook_metadata.watched_paths
        or (path_rule.watch_paths if path_rule is not None else ())
        or (repo_config.default_watch_paths if repo_config is not None else ()),
        include_notebook_file=repo_config.include_notebook_file
        if repo_config is not None
        else True,
        include_diff_when_dirty=repo_config.include_diff_when_dirty
        if repo_config is not None
        else True,
        target=LabArchivesTarget(
            notebook_name=target_notebook_name,
            root_path=target_root_path,
        ),
        metadata_template=metadata_template,
        stage_notebook_on_commit=repo_config.stage_notebook_on_commit
        if repo_config is not None
        else True,
        stage_watched_paths_on_commit=repo_config.stage_watched_paths_on_commit
        if repo_config is not None
        else False,
        commit_message_template=repo_config.commit_message_template
        if repo_config is not None
        else "snapshot: {notebook_name} {timestamp}",
    )


def _validate_path_rule_names(path_rules: tuple[PathRuleConfig, ...]) -> None:
    names: set[str] = set()
    for rule in path_rules:
        if rule.name in names:
            raise ConfigValidationError(
                f"Duplicate path rule name: {rule.name}.",
                code="duplicate_path_rule",
            )
        names.add(rule.name)


def _parse_target(
    *,
    notebook_name: str | None,
    root_path: str | None,
) -> LabArchivesTarget | None:
    if notebook_name is None and root_path is None:
        return None

    resolved_notebook_name = _parse_notebook_name(notebook_name or "Jupyter Snapshots")
    resolved_root_path = _parse_root_path(root_path or "Notebook Log")
    assert resolved_notebook_name is not None
    assert resolved_root_path is not None
    return LabArchivesTarget(
        notebook_name=resolved_notebook_name,
        root_path=resolved_root_path,
    )


def _parse_notebook_name(value: str | None) -> LabArchivesNotebookName | None:
    if value is None:
        return None
    return LabArchivesNotebookName(value)


def _parse_root_path(value: str | None) -> LabArchivesRootPath | None:
    if value is None:
        return None
    return LabArchivesRootPath(value)


def _parse_string_mapping(raw: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        normalized[str(key)] = require_str(value, field_name=f"mapping.{key}")
    return normalized

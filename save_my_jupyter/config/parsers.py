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
    expect,
    maybe,
    normalize_path,
    tuple_of,
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

    return parse_repo_config(expect(raw, Mapping, field="repo_config"))


def parse_repo_config(raw: Mapping[str, object]) -> RepoConfig:
    project = maybe(raw.get("project"), Mapping, field="project") or {}
    defaults = maybe(raw.get("defaults"), Mapping, field="defaults") or {}
    labarchives = maybe(raw.get("labarchives"), Mapping, field="labarchives") or {}
    git = maybe(raw.get("git"), Mapping, field="git") or {}

    project_name = expect(
        project.get("name", "save-my-jupyter"),
        str,
        field="project.name",
    )
    repo_root_strategy = expect(
        project.get("repo_root_strategy", "git"),
        str,
        field="project.repo_root_strategy",
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
        parse_path_rule(expect(item, Mapping, field="path_rule"))
        for item in path_rules_raw
    )
    _validate_path_rule_names(path_rules)

    return RepoConfig(
        project_name=project_name,
        repo_root_strategy=cast("Literal['git', 'fixed']", repo_root_strategy),
        default_all_cells_trigger=expect(
            defaults.get("all_cells_trigger", False),
            bool,
            field="defaults.all_cells_trigger",
        ),
        default_commit_mode=CommitMode(
            expect(
                defaults.get("commit_mode", CommitMode.PROMPT.value),
                str,
                field="defaults.commit_mode",
            )
        ),
        default_watch_paths=tuple(
            RelativeWatchPath(normalize_path(path))
            for path in tuple_of(
                defaults.get("watch_paths"),
                str,
                field="defaults.watch_paths",
            )
        ),
        include_notebook_file=expect(
            defaults.get("include_notebook_file", True),
            bool,
            field="defaults.include_notebook_file",
        ),
        include_diff_when_dirty=expect(
            defaults.get("include_diff_when_dirty", True),
            bool,
            field="defaults.include_diff_when_dirty",
        ),
        default_target=_parse_target(
            notebook_name=maybe(
                labarchives.get("target_notebook"),
                str,
                field="labarchives.target_notebook",
            ),
            root_path=maybe(
                labarchives.get("target_root_path"),
                str,
                field="labarchives.target_root_path",
            ),
        ),
        stage_notebook_on_commit=expect(
            git.get("stage_notebook_on_commit", True),
            bool,
            field="git.stage_notebook_on_commit",
        ),
        stage_watched_paths_on_commit=expect(
            git.get("stage_watched_paths_on_commit", False),
            bool,
            field="git.stage_watched_paths_on_commit",
        ),
        commit_message_template=expect(
            git.get("commit_message_template", "snapshot: {notebook_name} {timestamp}"),
            str,
            field="git.commit_message_template",
        ),
        path_rules=path_rules,
    )


def parse_path_rule(raw: Mapping[str, object]) -> PathRuleConfig:
    return PathRuleConfig(
        name=expect(raw.get("name"), str, field="path_rule.name"),
        match_paths=tuple(
            RelativeRepoPath(normalize_path(path))
            for path in tuple_of(
                raw.get("match_paths"),
                str,
                field="path_rule.match_paths",
            )
        ),
        watch_paths=tuple(
            RelativeWatchPath(normalize_path(path))
            for path in tuple_of(
                raw.get("watch_paths"),
                str,
                field="path_rule.watch_paths",
            )
        ),
        include_paths=tuple(
            RelativeWatchPath(normalize_path(path))
            for path in tuple_of(
                raw.get("include_paths"),
                str,
                field="path_rule.include_paths",
            )
        ),
        exclude_paths=tuple(
            RelativeWatchPath(normalize_path(path))
            for path in tuple_of(
                raw.get("exclude_paths"),
                str,
                field="path_rule.exclude_paths",
            )
        ),
        target=_parse_target(
            notebook_name=maybe(
                raw.get("labarchives_target_notebook"),
                str,
                field="path_rule.labarchives_target_notebook",
            ),
            root_path=maybe(
                raw.get("labarchives_target_root_path"),
                str,
                field="path_rule.labarchives_target_root_path",
            ),
        ),
        metadata_template=_parse_string_mapping(
            maybe(
                raw.get("metadata_template"),
                Mapping,
                field="path_rule.metadata_template",
            )
            or {}
        ),
    )


def parse_user_settings(raw: Mapping[str, object]) -> UserSettingsConfig:
    return UserSettingsConfig(
        default_commit_mode=CommitMode(
            expect(
                raw.get("defaultCommitMode", CommitMode.PROMPT.value),
                str,
                field="defaultCommitMode",
            )
        ),
        remember_commit_choice=expect(
            raw.get("rememberCommitChoice", False),
            bool,
            field="rememberCommitChoice",
        ),
        default_tags=tuple_of(raw.get("defaultTags"), str, field="defaultTags"),
        default_run_label=maybe(
            raw.get("defaultRunLabel"),
            str,
            field="defaultRunLabel",
        ),
        default_experiment_context=maybe(
            raw.get("defaultExperimentContext"),
            str,
            field="defaultExperimentContext",
        ),
    )


def parse_notebook_metadata(raw: Mapping[str, object]) -> NotebookMetadataConfig:
    return NotebookMetadataConfig(
        enabled=expect(raw.get("enabled", True), bool, field="enabled"),
        trigger_mode=TriggerMode.ALL_CELLS
        if expect(
            raw.get("all_cells_trigger", False),
            bool,
            field="all_cells_trigger",
        )
        else TriggerMode.MARKED_CELLS,
        trigger_cell_ids=frozenset(
            CellId(cell_id)
            for cell_id in tuple_of(
                raw.get("trigger_cell_ids"),
                str,
                field="trigger_cell_ids",
            )
        ),
        watched_paths=tuple(
            RelativeWatchPath(normalize_path(path))
            for path in tuple_of(raw.get("watched_paths"), str, field="watched_paths")
        ),
        labarchives_target_notebook=_parse_notebook_name(
            maybe(
                raw.get("labarchives_target_notebook"),
                str,
                field="labarchives_target_notebook",
            )
        ),
        labarchives_target_root_path=_parse_root_path(
            maybe(
                raw.get("labarchives_target_root_path"),
                str,
                field="labarchives_target_root_path",
            )
        ),
        default_metadata=_parse_string_mapping(
            maybe(raw.get("default_metadata"), Mapping, field="default_metadata") or {}
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
        normalized[str(key)] = expect(value, str, field=f"mapping.{key}")
    return normalized

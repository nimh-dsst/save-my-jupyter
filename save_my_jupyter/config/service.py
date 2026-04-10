from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from save_my_jupyter.config.parsers import (
    merge_effective_config,
    parse_notebook_metadata,
    parse_repo_config_file,
    parse_user_settings,
)
from save_my_jupyter.domain import (
    CommitMode,
    EffectiveConfig,
    NotebookMetadataConfig,
    NotebookPath,
    PathRuleConfig,
    RelativeRepoPath,
    RepoConfig,
    ResolvedPathRule,
    SnapshotRequest,
    UserId,
    UserSettingsConfig,
)
from save_my_jupyter.errors import ConfigValidationError
from save_my_jupyter.parsing import normalize_relative_path_text


class ConfigService:
    def find_repo_config(self, notebook_path: NotebookPath) -> Path | None:
        path = Path(notebook_path).resolve()
        search_root = path if path.is_dir() else path.parent
        for parent in (search_root, *search_root.parents):
            candidate = parent / ".save-my-jupyter.toml"
            if candidate.exists():
                return candidate
        return None

    def load_repo_config(self, notebook_path: NotebookPath) -> RepoConfig | None:
        config_path = self.find_repo_config(notebook_path)
        if config_path is None:
            return None
        return parse_repo_config_file(config_path)

    def load_user_settings(
        self,
        settings: Mapping[str, object] | None,
    ) -> UserSettingsConfig:
        return parse_user_settings(settings or {})

    def load_notebook_metadata(
        self,
        metadata: Mapping[str, object] | None,
    ) -> NotebookMetadataConfig:
        return parse_notebook_metadata(metadata or {})

    def resolve_path_rule(
        self,
        repo_config: RepoConfig,
        notebook_relpath: RelativeRepoPath,
    ) -> ResolvedPathRule | None:
        matches: list[tuple[int, PathRuleConfig]] = []
        relpath = str(notebook_relpath)
        for rule in repo_config.path_rules:
            specificity = _match_specificity(relpath, rule)
            if specificity > -1:
                matches.append((specificity, rule))

        if not matches:
            return None

        matches.sort(key=lambda item: item[0], reverse=True)
        if len(matches) > 1 and matches[0][0] == matches[1][0]:
            raise ConfigValidationError(
                "Multiple path rules match with the same specificity.",
                code="ambiguous_path_rule",
                context={"path": relpath},
            )

        _, rule = matches[0]
        return ResolvedPathRule(
            rule_name=rule.name,
            match_paths=rule.match_paths,
            watch_paths=rule.watch_paths,
            include_paths=rule.include_paths,
            exclude_paths=rule.exclude_paths,
            target=rule.target,
            metadata_template=rule.metadata_template,
        )

    def merge_config_layers(
        self,
        *,
        repo_config: RepoConfig | None,
        notebook_metadata: NotebookMetadataConfig,
        user_settings: UserSettingsConfig,
        path_rule: ResolvedPathRule | None,
        request_commit_mode: CommitMode,
    ) -> EffectiveConfig:
        path_rule_config = None
        if path_rule is not None:
            path_rule_config = PathRuleConfig(
                name=path_rule.rule_name,
                match_paths=path_rule.match_paths,
                watch_paths=path_rule.watch_paths,
                include_paths=path_rule.include_paths,
                exclude_paths=path_rule.exclude_paths,
                target=path_rule.target,
                metadata_template=path_rule.metadata_template,
            )

        return merge_effective_config(
            repo_config=repo_config,
            notebook_metadata=notebook_metadata,
            user_settings=user_settings,
            path_rule=path_rule_config,
            request_commit_mode=request_commit_mode,
        )

    def relative_notebook_path(
        self,
        *,
        notebook_path: NotebookPath,
        repo_root: Path | None,
    ) -> RelativeRepoPath | None:
        if repo_root is None:
            return None
        notebook = Path(notebook_path).resolve()
        return RelativeRepoPath(
            normalize_relative_path_text(
                str(notebook.relative_to(repo_root)).replace("\\", "/")
            )
        )

    def resolve_effective_config(
        self,
        *,
        request: SnapshotRequest,
        user_id: UserId,
        user_settings: Mapping[str, object] | None = None,
        notebook_metadata: Mapping[str, object] | None = None,
    ) -> tuple[
        RepoConfig | None,
        NotebookMetadataConfig,
        UserSettingsConfig,
        ResolvedPathRule | None,
        EffectiveConfig,
    ]:
        del user_id
        repo_config = self.load_repo_config(request.notebook_context.notebook_path)
        resolved_notebook_metadata = self.load_notebook_metadata(notebook_metadata)
        resolved_user_settings = self.load_user_settings(user_settings)
        path_rule = None
        if repo_config is not None:
            config_path = self.find_repo_config(request.notebook_context.notebook_path)
            repo_root = config_path.parent if config_path is not None else None
            relative_path = self.relative_notebook_path(
                notebook_path=request.notebook_context.notebook_path,
                repo_root=repo_root,
            )
            if relative_path is not None:
                path_rule = self.resolve_path_rule(repo_config, relative_path)

        effective_config = self.merge_config_layers(
            repo_config=repo_config,
            notebook_metadata=resolved_notebook_metadata,
            user_settings=resolved_user_settings,
            path_rule=path_rule,
            request_commit_mode=request.commit_mode,
        )
        return (
            repo_config,
            resolved_notebook_metadata,
            resolved_user_settings,
            path_rule,
            effective_config,
        )


def _match_specificity(relpath: str, rule: PathRuleConfig) -> int:
    matches = [
        len(str(match_path))
        for match_path in rule.match_paths
        if relpath == str(match_path) or relpath.startswith(f"{match_path}/")
    ]
    return max(matches, default=-1)

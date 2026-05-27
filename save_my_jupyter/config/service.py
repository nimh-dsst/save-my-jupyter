from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from save_my_jupyter.config.models import (
    EffectiveConfig,
    NotebookMetadataConfig,
    RepoConfig,
    RepoConfigBootstrapResult,
    ResolvedConfig,
    UserSettingsConfig,
)
from save_my_jupyter.config.parsers import (
    merge_effective_config,
    parse_notebook_metadata,
    parse_repo_config_file,
    parse_user_settings,
)
from save_my_jupyter.domain.enums import CommitMode
from save_my_jupyter.domain.models import SnapshotRequest
from save_my_jupyter.domain.types import NotebookPath, RelativeRepoPath
from save_my_jupyter.parsing import normalize_path


class ConfigService:
    def find_repo_config(self, notebook_path: NotebookPath) -> Path | None:
        config_root = self._resolve_config_root(
            notebook_path=notebook_path,
            repo_root=self._infer_repo_root(notebook_path),
        )
        candidate = config_root / ".save-my-jupyter.toml"
        return candidate if candidate.exists() else None

    def load_repo_config(self, notebook_path: NotebookPath) -> RepoConfig | None:
        config_path = self.find_repo_config(notebook_path)
        if config_path is None:
            return None
        return parse_repo_config_file(config_path)

    def suggested_repo_config_path(
        self,
        *,
        notebook_path: NotebookPath,
        repo_root: Path | None,
    ) -> Path:
        config_root = self._resolve_config_root(
            notebook_path=notebook_path,
            repo_root=repo_root,
        )
        return config_root / ".save-my-jupyter.toml"

    def ensure_repo_config(
        self,
        *,
        notebook_path: NotebookPath,
        repo_root: Path | None,
    ) -> RepoConfigBootstrapResult:
        config_path = self.suggested_repo_config_path(
            notebook_path=notebook_path,
            repo_root=repo_root,
        )
        if config_path.exists():
            return RepoConfigBootstrapResult(
                config_path=config_path,
                root_directory=config_path.parent,
                status="exists",
            )

        config_path.write_text(
            self.render_repo_config_template(
                notebook_path=notebook_path,
                repo_root=repo_root,
            ),
            encoding="utf-8",
        )
        return RepoConfigBootstrapResult(
            config_path=config_path,
            root_directory=config_path.parent,
            status="created",
        )

    def render_repo_config_template(
        self,
        *,
        notebook_path: NotebookPath,
        repo_root: Path | None,
    ) -> str:
        config_path = self.suggested_repo_config_path(
            notebook_path=notebook_path,
            repo_root=repo_root,
        )
        project_name = config_path.parent.name or "save-my-jupyter"
        lines = [
            "# Save My Jupyter starter config",
            (
                "# Edit the LabArchives target names and watched paths to match "
                "your project."
            ),
            "# Any target_root_path setting supports these substitutions:",
            "# {name}, {user_id}, {user_email}, {repo_name}, {notebook_name},",
            "# {notebook_stem}, {relative_notebook_path}, {scope_path},",
            "# {scope_name}, {run_label}, {experiment_context}, {timestamp},",
            "# {date}, {time}, {source}, {commit_hash}",
            "",
            "[project]",
            f'name = "{project_name}"',
            f'repo_root_strategy = "{"git" if repo_root is not None else "fixed"}"',
            "",
            "[defaults]",
            "all_cells_trigger = false",
            'commit_mode = "prompt"',
            'watch_paths = ["**/*.py"]',
            "include_notebook_file = true",
            "include_diff_when_dirty = true",
            "",
            "[labarchives]",
            'target_notebook = "Jupyter Snapshots"',
            "# Substitutions: {name}, {user_id}, {user_email}, {repo_name},",
            "# {notebook_name}, {notebook_stem}, {relative_notebook_path},",
            "# {scope_path}, {scope_name}, {run_label},",
            "# {experiment_context}, {timestamp}, {date}, {time},",
            "# {source}, {commit_hash}",
            'target_root_path = "Notebook Log/{name}/{relative_notebook_path}"',
            "",
            "[git]",
            "stage_notebook_on_commit = true",
            "stage_watched_paths_on_commit = false",
            "# Substitutions: {notebook_name}, {timestamp}",
            'commit_message_template = "snapshot: {notebook_name} {timestamp}"',
        ]
        return "\n".join(lines) + "\n"

    def _resolve_config_root(
        self,
        *,
        notebook_path: NotebookPath,
        repo_root: Path | None,
    ) -> Path:
        notebook = Path(notebook_path).resolve()
        notebook_dir = notebook if notebook.is_dir() else notebook.parent
        resolved_repo_root = repo_root.resolve() if repo_root is not None else None

        current = notebook_dir
        while True:
            if (current / "pyproject.toml").exists():
                return current
            if (current / "package.json").exists():
                return current
            if resolved_repo_root is not None and current == resolved_repo_root:
                break
            if current.parent == current:
                break
            current = current.parent

        return resolved_repo_root if resolved_repo_root is not None else notebook_dir

    def _infer_repo_root(self, notebook_path: NotebookPath) -> Path | None:
        notebook = Path(notebook_path).resolve()
        current = notebook if notebook.is_dir() else notebook.parent

        while True:
            git_marker = current / ".git"
            if git_marker.exists():
                return current
            if current.parent == current:
                return None
            current = current.parent

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

    def merge_config_layers(
        self,
        *,
        repo_config: RepoConfig | None,
        notebook_metadata: NotebookMetadataConfig,
        user_settings: UserSettingsConfig,
        request_commit_mode: CommitMode,
    ) -> EffectiveConfig:
        return merge_effective_config(
            repo_config=repo_config,
            notebook_metadata=notebook_metadata,
            user_settings=user_settings,
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
            normalize_path(str(notebook.relative_to(repo_root)).replace("\\", "/"))
        )

    def resolve_effective_config(
        self,
        *,
        request: SnapshotRequest,
        user_settings: Mapping[str, object] | None = None,
        notebook_metadata: Mapping[str, object] | None = None,
    ) -> ResolvedConfig:
        repo_config = self.load_repo_config(request.notebook_context.notebook_path)
        resolved_notebook_metadata = self.load_notebook_metadata(notebook_metadata)
        resolved_user_settings = self.load_user_settings(user_settings)
        effective_config = self.merge_config_layers(
            repo_config=repo_config,
            notebook_metadata=resolved_notebook_metadata,
            user_settings=resolved_user_settings,
            request_commit_mode=request.commit_mode,
        )
        return ResolvedConfig(
            repo_config=repo_config,
            notebook_metadata=resolved_notebook_metadata,
            user_settings=resolved_user_settings,
            effective_config=effective_config,
        )

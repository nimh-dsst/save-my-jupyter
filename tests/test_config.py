from __future__ import annotations

import shutil
from pathlib import Path

from save_my_jupyter.config.parsers import parse_notebook_metadata, parse_repo_config
from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.domain import (
    CommitMode,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    UserMetadata,
)


def test_parse_repo_config_without_path_rules() -> None:
    repo_config = parse_repo_config(
        {
            "project": {"name": "Example", "repo_root_strategy": "git"},
            "defaults": {
                "all_cells_trigger": True,
                "commit_mode": "always",
                "watch_paths": ["outputs", "reports/result.csv"],
            },
            "labarchives": {
                "target_notebook": "Snapshots",
                "target_root_path": "Runs",
            },
        }
    )

    assert repo_config.project_name == "Example"
    assert repo_config.default_all_cells_trigger is True
    assert str(repo_config.default_watch_paths[0]) == "outputs"


def test_parse_notebook_metadata() -> None:
    metadata = parse_notebook_metadata(
        {
            "enabled": True,
            "all_cells_trigger": True,
            "trigger_cell_ids": ["cell-1"],
            "watched_paths": ["outputs/result.csv"],
            "labarchives_target_notebook": "Snapshots",
            "labarchives_target_root_path": "Runs",
            "default_metadata": {"owner": "alice"},
        }
    )

    assert metadata.enabled is True
    assert str(next(iter(metadata.trigger_cell_ids))) == "cell-1"
    assert str(metadata.watched_paths[0]) == "outputs/result.csv"
    assert metadata.default_metadata["owner"] == "alice"


def test_config_service_creates_starter_repo_config() -> None:
    repo_root = Path.cwd() / ".test_config_bootstrap_repo"
    shutil.rmtree(repo_root, ignore_errors=True)
    try:
        (repo_root / ".git").mkdir(parents=True)
        notebook_dir = repo_root / "analysis"
        notebook_dir.mkdir(parents=True)
        notebook_path = notebook_dir / "work.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")

        service = ConfigService()
        result = service.ensure_repo_config(
            notebook_path=NotebookPath(str(notebook_path)),
            repo_root=repo_root,
        )

        assert result.status == "created"
        assert result.config_path == repo_root / ".save-my-jupyter.toml"
        repo_config = service.load_repo_config(NotebookPath(str(notebook_path)))
        assert repo_config is not None
        assert repo_config.project_name == repo_root.name
        starter_config = result.config_path.read_text(encoding="utf-8")
        assert (
            'target_root_path = "Notebook Log/{name}/{relative_notebook_path}"'
            in starter_config
        )
        assert "# Any target_root_path setting supports these substitutions:" in (
            starter_config
        )
        assert "{name}" in starter_config
        assert "{relative_notebook_path}" in starter_config
        assert 'target_root_path = "Notebook Log/{user_email}' not in starter_config
        assert "[[path_rule]]" not in starter_config
        assert "# Substitutions: {notebook_name}, {timestamp}" in starter_config
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_config_service_prefers_nearest_project_root_for_starter_config() -> None:
    repo_root = Path.cwd() / ".test_config_monorepo"
    shutil.rmtree(repo_root, ignore_errors=True)
    try:
        project_root = repo_root / "save-my-jupyter-test"
        notebook_dir = project_root / "notebooks"
        notebook_dir.mkdir(parents=True)
        (project_root / "pyproject.toml").write_text(
            '[project]\nname = "package-display-name"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        notebook_path = notebook_dir / "work.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")

        service = ConfigService()
        result = service.ensure_repo_config(
            notebook_path=NotebookPath(str(notebook_path)),
            repo_root=repo_root,
        )

        assert result.status == "created"
        assert result.config_path == project_root / ".save-my-jupyter.toml"
        assert result.root_directory == project_root
        starter_config = result.config_path.read_text(encoding="utf-8")
        assert 'name = "save-my-jupyter-test"' in starter_config
        assert 'name = "package-display-name"' not in starter_config
        assert "[[path_rule]]" not in starter_config
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_config_service_does_not_inherit_parent_project_config() -> None:
    repo_root = Path.cwd() / ".test_config_inheritance_repo"
    shutil.rmtree(repo_root, ignore_errors=True)
    try:
        (repo_root / ".git").mkdir(parents=True)
        (repo_root / ".save-my-jupyter.toml").write_text(
            """
[project]
name = "parent"
""".strip(),
            encoding="utf-8",
        )

        project_root = repo_root / "child-project"
        notebook_dir = project_root / "notebooks"
        notebook_dir.mkdir(parents=True)
        (project_root / "pyproject.toml").write_text(
            '[project]\nname = "child-project"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        notebook_path = notebook_dir / "work.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")

        service = ConfigService()

        assert service.find_repo_config(NotebookPath(str(notebook_path))) is None
        assert service.load_repo_config(NotebookPath(str(notebook_path))) is None
        assert (
            service.suggested_repo_config_path(
                notebook_path=NotebookPath(str(notebook_path)),
                repo_root=repo_root,
            )
            == project_root / ".save-my-jupyter.toml"
        )
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_config_service_resolve_effective_config_returns_named_result() -> None:
    root = Path.cwd() / ".test_resolved_config"
    shutil.rmtree(root, ignore_errors=True)
    try:
        notebook_path = root / "analysis.ipynb"
        notebook_path.parent.mkdir(parents=True)
        notebook_path.write_text("{}", encoding="utf-8")

        service = ConfigService()
        resolved_config = service.resolve_effective_config(
            request=ManualSnapshotRequest(
                notebook_context=NotebookContext(
                    notebook_path=NotebookPath(str(notebook_path)),
                    notebook_name=notebook_path.name,
                ),
                commit_mode=CommitMode.PROMPT,
                user_metadata=UserMetadata(),
            ),
            notebook_metadata={"watched_paths": ["outputs"]},
        )

        assert resolved_config.repo_config is None
        assert str(resolved_config.notebook_metadata.watched_paths[0]) == "outputs"
        assert str(resolved_config.effective_config.watched_paths[0]) == "outputs"
    finally:
        shutil.rmtree(root, ignore_errors=True)

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from save_my_jupyter.config.parsers import parse_notebook_metadata, parse_repo_config
from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.domain import NotebookPath
from save_my_jupyter.errors import ConfigValidationError


def test_parse_repo_config_with_path_rules() -> None:
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
            "path_rule": [
                {
                    "name": "analysis",
                    "match_paths": ["analysis"],
                    "watch_paths": ["analysis/outputs"],
                }
            ],
        }
    )

    assert repo_config.project_name == "Example"
    assert repo_config.default_all_cells_trigger is True
    assert str(repo_config.default_watch_paths[0]) == "outputs"
    assert repo_config.path_rules[0].name == "analysis"


def test_parse_repo_config_rejects_duplicate_rule_names() -> None:
    with pytest.raises(ConfigValidationError, match="Duplicate path rule name"):
        parse_repo_config(
            {
                "project": {"name": "Example"},
                "path_rule": [
                    {"name": "dup", "match_paths": ["analysis"]},
                    {"name": "dup", "match_paths": ["reports"]},
                ],
            }
        )


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


def test_config_service_resolves_most_specific_path_rule() -> None:
    repo_root = Path.cwd() / ".test_config_repo"
    shutil.rmtree(repo_root, ignore_errors=True)
    try:
        notebook_dir = repo_root / "analysis" / "deep"
        notebook_dir.mkdir(parents=True)
        notebook_path = notebook_dir / "work.ipynb"
        notebook_path.write_text("{}", encoding="utf-8")
        (repo_root / ".save-my-jupyter.toml").write_text(
            """
[project]
name = "Example"

[[path_rule]]
name = "analysis"
match_paths = ["analysis"]

[[path_rule]]
name = "deep"
match_paths = ["analysis/deep"]
""".strip(),
            encoding="utf-8",
        )

        service = ConfigService()
        repo_config = service.load_repo_config(NotebookPath(str(notebook_path)))
        assert repo_config is not None

        relative_path = service.relative_notebook_path(
            notebook_path=NotebookPath(str(notebook_path)),
            repo_root=repo_root,
        )
        assert relative_path is not None

        path_rule = service.resolve_path_rule(repo_config, relative_path)
        assert path_rule is not None
        assert path_rule.rule_name == "deep"
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def test_config_service_creates_starter_repo_config() -> None:
    repo_root = Path.cwd() / ".test_config_bootstrap_repo"
    shutil.rmtree(repo_root, ignore_errors=True)
    try:
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
        assert repo_config.path_rules[0].name == "analysis"
        assert str(repo_config.path_rules[0].match_paths[0]) == "analysis"
        starter_config = result.config_path.read_text(encoding="utf-8")
        assert (
            'target_root_path = "Notebook Log/{user_id}/{scope_path}"'
            in starter_config
        )
        assert "{path_rule_name}" in starter_config
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
            '[project]\nname = "save-my-jupyter-test"\nversion = "0.1.0"\n',
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
        assert 'match_paths = ["notebooks"]' in starter_config
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)

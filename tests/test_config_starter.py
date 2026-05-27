from __future__ import annotations

import pytest
from save_my_jupyter.application.config.starter import (
    INFERRED_TARGET_ROOT_PATH,
    ensure_starter_config,
    inspect_starter_config,
)
from save_my_jupyter.domain.errors import SnapshotError


def test_root_notebook_starter_config_is_written_under_server_root(tmp_path) -> None:
    result = ensure_starter_config(server_root=tmp_path, notebook_path="analysis.ipynb")

    assert result.status == "created"
    assert result.config_path == ".save-my-jupyter.toml"
    assert result.root_directory == ""
    content = (tmp_path / ".save-my-jupyter.toml").read_text(encoding="utf-8")
    assert f'target_root_path = "{INFERRED_TARGET_ROOT_PATH}"' in content
    assert f'name = "{tmp_path.name}"' in content


def test_starter_config_is_written_at_discovered_project_marker(tmp_path) -> None:
    project = tmp_path / "project"
    notebooks = project / "notebooks"
    notebooks.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    result = ensure_starter_config(
        server_root=tmp_path, notebook_path="project/notebooks/run.ipynb"
    )

    assert result.status == "created"
    assert result.config_path == "project/.save-my-jupyter.toml"
    assert (project / ".save-my-jupyter.toml").is_file()
    assert 'name = "project"' in (project / ".save-my-jupyter.toml").read_text(
        encoding="utf-8"
    )


def test_starter_config_does_not_overwrite_existing_config(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".save-my-jupyter.toml"
    config.write_text("existing = true\n", encoding="utf-8")

    result = ensure_starter_config(
        server_root=tmp_path, notebook_path="project/run.ipynb"
    )

    assert result.status == "exists"
    assert result.config_path == "project/.save-my-jupyter.toml"
    assert config.read_text(encoding="utf-8") == "existing = true\n"


def test_starter_config_inspection_reports_missing_root_config(tmp_path) -> None:
    result = inspect_starter_config(
        server_root=tmp_path, notebook_path="analysis.ipynb"
    )

    assert result.config_path == ".save-my-jupyter.toml"
    assert result.exists is False
    assert result.root_directory == ""


def test_starter_config_rejects_paths_outside_server_root(tmp_path) -> None:
    with pytest.raises(SnapshotError) as exc_info:
        ensure_starter_config(server_root=tmp_path, notebook_path="../analysis.ipynb")

    assert exc_info.value.code == "invalid_notebook_path"

"""Project-level `.save-my-jupyter.toml` discovery shared by preview and
snapshot execution (contract C-CONFIG-03)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.application.config.parse import parse_repo_config
from save_my_jupyter.domain.errors import SnapshotError

if TYPE_CHECKING:
    from save_my_jupyter.domain.config import RepoConfig
    from save_my_jupyter.domain.types import NotebookPath, RepoRootPath
    from save_my_jupyter.ports import FileSystem

REPO_CONFIG_FILENAME = ".save-my-jupyter.toml"

_PROJECT_SENTINELS = ("pyproject.toml", "package.json", ".git")


@dataclass(frozen=True, slots=True)
class RepoConfigDiscovery:
    root: Path
    path: Path
    loaded: bool
    config: RepoConfig | None


def discover_repo_config(
    *,
    filesystem: FileSystem,
    notebook_path: NotebookPath,
    repo_root: RepoRootPath | None,
) -> RepoConfigDiscovery:
    root = _project_root(filesystem, notebook_path, repo_root)
    path = root / REPO_CONFIG_FILENAME
    if not filesystem.is_file(path):
        return RepoConfigDiscovery(root=root, path=path, loaded=False, config=None)
    try:
        text = filesystem.read_bytes(path).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SnapshotError(
            "Could not parse .save-my-jupyter.toml.",
            code="repo_config_parse_failed",
            context={"path": str(path), "error": str(exc)},
        ) from exc
    return RepoConfigDiscovery(
        root=root,
        path=path,
        loaded=True,
        config=parse_repo_config(text, default_project_name=root.name),
    )


def _project_root(
    filesystem: FileSystem,
    notebook_path: NotebookPath,
    repo_root: RepoRootPath | None,
) -> Path:
    if repo_root is not None:
        return Path(repo_root)
    start = Path(notebook_path).resolve().parent
    ancestors = (start, *start.parents)
    for candidate in ancestors:
        if any(
            filesystem.exists(candidate / sentinel) for sentinel in _PROJECT_SENTINELS
        ):
            return candidate
        if filesystem.is_file(candidate / REPO_CONFIG_FILENAME):
            return candidate
    return start

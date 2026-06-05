"""Starter `.save-my-jupyter.toml` creation for the panel setup action."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from save_my_jupyter.domain.errors import SnapshotError

REPO_CONFIG_FILENAME = ".save-my-jupyter.toml"
INFERRED_TARGET_ROOT_PATH = (
    "Notebook Log/{user_email}/{project_name}/{relative_notebook_path}"
)

_DEFAULT_PROJECT_NAME = "save-my-jupyter"
_PROJECT_MARKERS = (".git", "pyproject.toml", "package.json")


@dataclass(frozen=True, slots=True)
class StarterConfigInspection:
    config_path: str
    exists: bool
    root_directory: str


@dataclass(frozen=True, slots=True)
class StarterConfigResult:
    config_path: str
    message: str
    root_directory: str
    status: str


def inspect_starter_config(
    *, server_root: Path, notebook_path: str
) -> StarterConfigInspection:
    root = server_root.resolve()
    normalized_notebook_path = _normalize_notebook_path(notebook_path)
    return _inspect_starter_config(root, normalized_notebook_path)


def ensure_starter_config(
    *, server_root: Path, notebook_path: str
) -> StarterConfigResult:
    root = server_root.resolve()
    normalized_notebook_path = _normalize_notebook_path(notebook_path)
    inspection = _inspect_starter_config(root, normalized_notebook_path)
    if inspection.exists:
        return StarterConfigResult(
            config_path=inspection.config_path,
            message=f"Config already exists at {inspection.config_path}.",
            root_directory=inspection.root_directory,
            status="exists",
        )

    config_file = _filesystem_path(root, inspection.config_path)
    project_name = _project_name(root=root, root_directory=inspection.root_directory)
    try:
        config_file.write_text(
            build_starter_config(project_name=project_name), encoding="utf-8"
        )
    except OSError as exc:
        raise SnapshotError(
            "Unable to create the starter config.",
            code="config_init_failed",
            context={"path": inspection.config_path},
        ) from exc
    return StarterConfigResult(
        config_path=inspection.config_path,
        message=f"Created starter config at {inspection.config_path}.",
        root_directory=inspection.root_directory,
        status="created",
    )


def build_starter_config(*, project_name: str) -> str:
    escaped_project_name = _toml_string(project_name or _DEFAULT_PROJECT_NAME)
    return "\n".join(
        [
            "# Save My Jupyter starter configuration.",
            "# Shared defaults for snapshots created from this workspace.",
            "",
            "[project]",
            f'name = "{escaped_project_name}"',
            'repo_root_strategy = "git"',
            "",
            "[defaults]",
            'commit_mode = "ask"',
            "all_cells_trigger = false",
            "watch_paths = []",
            "include_notebook_file = true",
            "include_diff_when_dirty = true",
            "",
            "[defaults.metadata]",
            "# Shared metadata fields added to every snapshot.",
            '# audience = "team"',
            "",
            "[labarchives]",
            'target_notebook = "Jupyter Snapshots"',
            f'target_root_path = "{INFERRED_TARGET_ROOT_PATH}"',
            "",
            "[git]",
            'commit_message_template = "snapshot: {notebook_name} {timestamp}"',
            "stage_notebook_on_commit = true",
            "stage_watched_paths_on_commit = true",
            "",
        ]
    )


def _inspect_starter_config(root: Path, notebook_path: str) -> StarterConfigInspection:
    root_directory = _resolve_config_root(root, notebook_path)
    config_path = _join_jupyter_path(root_directory, REPO_CONFIG_FILENAME)
    return StarterConfigInspection(
        config_path=config_path,
        exists=_path_exists(root, config_path),
        root_directory=root_directory,
    )


def _resolve_config_root(root: Path, notebook_path: str) -> str:
    directories = _ancestor_directories(notebook_path)
    for directory in directories:
        if _path_exists(root, _join_jupyter_path(directory, REPO_CONFIG_FILENAME)):
            return directory
        if _has_project_marker(root, directory):
            return directory
    return _notebook_directory(notebook_path)


def _has_project_marker(root: Path, directory: str) -> bool:
    return any(
        _path_exists(root, _join_jupyter_path(directory, marker))
        for marker in _PROJECT_MARKERS
    )


def _ancestor_directories(notebook_path: str) -> list[str]:
    start = _notebook_directory(notebook_path)
    directories = [start]
    current = start
    while current != "":
        current = _parent_directory(current)
        directories.append(current)
    return directories


def _notebook_directory(notebook_path: str) -> str:
    return _parent_directory(notebook_path)


def _parent_directory(path: str) -> str:
    parent = PurePosixPath(path).parent
    return "" if str(parent) == "." else parent.as_posix()


def _normalize_notebook_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if (
        normalized == ""
        or normalized.startswith("/")
        or _has_windows_drive_prefix(normalized)
    ):
        raise SnapshotError(
            "notebookPath must be a relative .ipynb path.",
            code="invalid_notebook_path",
            context={"path": path},
        )
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise SnapshotError(
            "notebookPath must stay within the Jupyter server root.",
            code="invalid_notebook_path",
            context={"path": path},
        )
    normalized = "/".join(parts)
    if PurePosixPath(normalized).suffix.lower() != ".ipynb":
        raise SnapshotError(
            "notebookPath must point to an .ipynb file.",
            code="invalid_notebook_path",
            context={"path": path},
        )
    return normalized


def _path_exists(root: Path, relative_path: str) -> bool:
    try:
        return _filesystem_path(root, relative_path).exists()
    except OSError:
        return False


def _filesystem_path(root: Path, relative_path: str) -> Path:
    if relative_path == "":
        candidate = root
    else:
        candidate = root.joinpath(*PurePosixPath(relative_path).parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SnapshotError(
            "Config path must stay within the Jupyter server root.",
            code="path_escapes_root",
            context={"path": relative_path},
        ) from exc
    return candidate


def _join_jupyter_path(directory: str, name: str) -> str:
    return name if directory == "" else f"{directory}/{name}"


def _project_name(*, root: Path, root_directory: str) -> str:
    if root_directory != "":
        candidate = root_directory.split("/")[-1]
        if candidate:
            return candidate
    return root.name or _DEFAULT_PROJECT_NAME


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _has_windows_drive_prefix(path: str) -> bool:
    return len(path) >= 2 and path[0].isalpha() and path[1] == ":"

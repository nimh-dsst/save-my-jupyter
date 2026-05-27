"""Build the advisory snapshot preview (target CONFIGURE/CAPTURE, contracts
C-CONFIG-02/11). Resolves config for a request and plans what a snapshot would
contain, returning the plan plus per-field provenance so the panel can label
inferred values. Read-only orchestration over ports (git inspector, filesystem);
it never delivers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.application.config import (
    parse_notebook_metadata,
    parse_repo_config,
    resolve_effective_config,
)
from save_my_jupyter.application.snapshot.directives import parse_directives
from save_my_jupyter.application.snapshot.notebook_content import outline_notebook
from save_my_jupyter.application.snapshot.plan import plan_capture
from save_my_jupyter.domain.capture import CapturePlan
from save_my_jupyter.domain.enums import CommitMode

if TYPE_CHECKING:
    from save_my_jupyter.domain.config import UserSettingsConfig
    from save_my_jupyter.domain.provenance import ConfigLayer
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.ports import FileSystem, GitInspector

_REPO_CONFIG_FILENAME = ".save-my-jupyter.toml"


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviewResult:
    plan: CapturePlan
    provenance: Mapping[str, ConfigLayer]
    source: str


def build_preview(
    request: SnapshotRequest,
    *,
    git_inspector: GitInspector,
    filesystem: FileSystem,
    user_settings: UserSettingsConfig,
) -> PreviewResult:
    context = request.notebook_context
    repo = git_inspector.resolve_repo(context.notebook_path)
    notebook_json = request.notebook_content or _load_notebook_json(
        filesystem, str(context.notebook_path)
    )
    source = "frontend" if request.notebook_content is not None else "disk"

    resolved = resolve_effective_config(
        request_commit_mode=request.commit_mode,
        notebook=parse_notebook_metadata(_notebook_metadata(notebook_json)),
        user=user_settings,
        repo=_load_repo_config(filesystem, repo.repo_root),
    )
    effective = resolved.effective
    will_commit = effective.commit_mode is CommitMode.ALWAYS and repo.is_dirty
    plan = plan_capture(
        config=effective,
        outline=outline_notebook(notebook_json),
        source=request.source,
        directive=parse_directives(_cell_sources(notebook_json)),
        repo_dirty=repo.is_dirty,
        will_create_commit=will_commit,
        ui_tags=request.metadata.tags,
        ui_run_label=request.metadata.run_label,
        default_tags=user_settings.default_tags,
    )
    return PreviewResult(plan=plan, provenance=resolved.provenance, source=source)


def _load_repo_config(filesystem: FileSystem, repo_root: str | None):
    if repo_root is None:
        return None
    config_path = Path(repo_root) / _REPO_CONFIG_FILENAME
    if not filesystem.is_file(config_path):
        return None
    text = filesystem.read_bytes(config_path).decode("utf-8")
    return parse_repo_config(text, default_project_name=Path(repo_root).name)


def _load_notebook_json(
    filesystem: FileSystem, notebook_path: str
) -> Mapping[str, object]:
    path = Path(notebook_path)
    if not filesystem.is_file(path):
        return {}
    return _as_dict(json.loads(filesystem.read_bytes(path).decode("utf-8"))) or {}


def _notebook_metadata(notebook_json: Mapping[str, object]) -> Mapping[str, object]:
    metadata = _as_dict(notebook_json.get("metadata"))
    if metadata is None:
        return {}
    return _as_dict(metadata.get("save_my_jupyter")) or {}


def _cell_sources(notebook_json: Mapping[str, object]) -> list[str]:
    cells = notebook_json.get("cells")
    if not isinstance(cells, list):
        return []
    sources: list[str] = []
    for cell in cells:
        normalized = _as_dict(cell)
        if normalized is not None:
            sources.append(_join_source(normalized.get("source")))
    return sources


def _join_source(source: object) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return ""


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): nested for key, nested in value.items()}

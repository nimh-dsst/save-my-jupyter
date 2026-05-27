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
    resolve_effective_config,
)
from save_my_jupyter.application.config.discovery import discover_repo_config
from save_my_jupyter.application.snapshot.directives import parse_directives
from save_my_jupyter.application.snapshot.guards import (
    NOTEBOOK_MAX_BYTES,
    enforce_size_cap,
)
from save_my_jupyter.application.snapshot.notebook_content import outline_notebook
from save_my_jupyter.application.snapshot.plan import plan_capture
from save_my_jupyter.domain.capture import CapturePlan
from save_my_jupyter.domain.enums import CommitMode
from save_my_jupyter.domain.errors import SnapshotError

if TYPE_CHECKING:
    from save_my_jupyter.domain.config import (
        EffectiveConfig,
        RepoConfig,
        UserSettingsConfig,
    )
    from save_my_jupyter.domain.provenance import ConfigLayer
    from save_my_jupyter.domain.repo import RepoContext
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.ports import FileSystem, GitInspector


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviewResult:
    plan: CapturePlan
    provenance: Mapping[str, ConfigLayer]
    effective: EffectiveConfig
    repo: RepoContext
    repo_config_path: str | None
    repo_config_loaded: bool
    notes: str | None
    extra_fields: Mapping[str, str]
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
    repo_config = discover_repo_config(
        filesystem=filesystem,
        notebook_path=context.notebook_path,
        repo_root=repo.repo_root,
    )

    resolved = resolve_effective_config(
        request_commit_mode=request.commit_mode,
        request_watched_paths=request.watched_paths,
        notebook=parse_notebook_metadata(_notebook_metadata(notebook_json)),
        user=user_settings,
        repo=repo_config.config,
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
        default_tags=_default_tags(user_settings, repo_config.config),
        default_run_label=user_settings.default_run_label,
    )
    return PreviewResult(
        plan=plan,
        provenance=resolved.provenance,
        effective=effective,
        repo=repo,
        repo_config_path=str(repo_config.path),
        repo_config_loaded=repo_config.loaded,
        notes=request.metadata.notes,
        extra_fields=request.metadata.extra_fields,
        source=source,
    )


def _default_tags(
    user_settings: UserSettingsConfig, repo_config: RepoConfig | None
) -> tuple[str, ...]:
    repo_tags = repo_config.default_tags if repo_config is not None else ()
    return (*repo_tags, *user_settings.default_tags)


def _load_notebook_json(
    filesystem: FileSystem, notebook_path: str
) -> Mapping[str, object]:
    path = Path(notebook_path)
    if not filesystem.is_file(path):
        return {}
    try:
        raw = filesystem.read_bytes(path)
    except OSError as exc:
        raise SnapshotError(
            "Unable to read notebook artifact.",
            code="notebook_artifact_parse_failed",
            context={"path": str(path)},
        ) from exc
    enforce_size_cap(
        size_bytes=len(raw),
        max_bytes=NOTEBOOK_MAX_BYTES,
        code="notebook_artifact_too_large",
        path=path,
    )
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(
            "Unable to parse notebook artifact.",
            code="notebook_artifact_parse_failed",
            context={"path": str(path)},
        ) from exc
    return _as_dict(loaded) or {}


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

"""The snapshot execution pipeline (target CAPTURE -> DELIVER -> CONFIRM): the
function the worker runs for one job. It resolves config, captures artifacts,
optionally commits, builds the bundle, and delivers it, recording the Activity
row via execute_snapshot. All IO is through injected ports, so it is testable
end-to-end with fakes.

Known follow-ups: the working-tree diff artifact is not yet wired (the filter
exists, raw generation does not), and trigger run_outcome relies on a default
until the request carries per-run success."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.application.config import (
    parse_notebook_metadata,
    parse_repo_config,
    resolve_effective_config,
)
from save_my_jupyter.application.snapshot.build import (
    build_snapshot_bundle,
    format_directory_name,
)
from save_my_jupyter.application.snapshot.capture_reader import gather_watched_files
from save_my_jupyter.application.snapshot.commit_url import build_commit_url
from save_my_jupyter.application.snapshot.directives import parse_directives
from save_my_jupyter.application.snapshot.execute import (
    SnapshotContext,
    execute_snapshot,
)
from save_my_jupyter.application.snapshot.notebook_content import (
    extract_figures,
    outline_notebook,
    summarize_execution,
)
from save_my_jupyter.application.snapshot.plan import plan_capture
from save_my_jupyter.application.snapshot.target_path import render_target_path
from save_my_jupyter.domain.artifacts import NotebookPayload
from save_my_jupyter.domain.config import EffectiveConfig, LabArchivesTarget
from save_my_jupyter.domain.delivery import SnapshotMetadata
from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    CommitHash,
    LabArchivesRootPath,
    NotebookPath,
    RelativeRepoPath,
    SnapshotId,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from save_my_jupyter.domain.activity import ActivityRecord
    from save_my_jupyter.domain.config import RepoConfig, UserSettingsConfig
    from save_my_jupyter.domain.repo import RepoContext
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.ports import (
        ActivityStore,
        Clock,
        Delivery,
        FileSystem,
        GitInspector,
        GitMutator,
    )

_REPO_CONFIG_FILENAME = ".save-my-jupyter.toml"


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineDependencies:
    git_inspector: GitInspector
    git_mutator: GitMutator
    filesystem: FileSystem
    delivery: Delivery
    activity: ActivityStore
    clock: Clock
    user_settings: UserSettingsConfig
    user_email: str
    user_id: str
    extension_version: str


def run_snapshot_pipeline(
    job_id: str, request: SnapshotRequest, deps: PipelineDependencies
) -> ActivityRecord:
    context = request.notebook_context
    repo = deps.git_inspector.resolve_repo(context.notebook_path)

    repo_config = _load_repo_config(deps, repo.repo_root)
    resolved = resolve_effective_config(
        request_commit_mode=request.commit_mode,
        notebook=parse_notebook_metadata(_notebook_metadata(request)),
        user=deps.user_settings,
        repo=repo_config,
    )
    effective = resolved.effective

    notebook_json = request.notebook_content or _load_notebook_json(
        deps, context.notebook_path
    )
    directive = parse_directives(_cell_sources(notebook_json))
    figures = extract_figures(notebook_json)
    outline = outline_notebook(notebook_json)

    will_commit = effective.commit_mode is CommitMode.ALWAYS and repo.is_dirty
    plan = plan_capture(
        config=effective,
        outline=outline,
        source=request.source,
        directive=directive,
        repo_dirty=repo.is_dirty,
        will_create_commit=will_commit,
        ui_tags=request.metadata.tags,
        ui_run_label=request.metadata.run_label,
        default_tags=deps.user_settings.default_tags,
        triggering_cell_source=_triggering_cell_source(notebook_json, request),
    )

    timestamp = deps.clock.now()
    commit_hash, commit_status = _maybe_commit(
        deps, request, effective, repo, timestamp=timestamp, will_commit=will_commit
    )
    snapshot_id = SnapshotId(uuid.uuid4().hex[:12])
    directory_name = format_directory_name(timestamp=timestamp, snapshot_id=snapshot_id)

    capture_root = (
        Path(repo.repo_root)
        if repo.repo_root
        else Path(context.notebook_path).resolve().parent
    )
    watched = gather_watched_files(
        watched_paths=effective.watched_paths,
        capture_root=capture_root,
        filesystem=deps.filesystem,
    )

    run_outcome = (
        RunOutcome.NOT_APPLICABLE
        if request.source is SnapshotSource.MANUAL
        else RunOutcome.SUCCESS
    )
    notebook_path = str(repo.relative_notebook_path or context.notebook_path)
    commit_url = build_commit_url(repo.remote_url, commit_hash)
    metadata = SnapshotMetadata(
        notebook_name=context.notebook_name,
        notebook_path=notebook_path,
        source=request.source,
        run_outcome=run_outcome,
        snapshot_id=snapshot_id,
        run_fingerprint=None,
        trigger_cells=context.triggered_cell_ids,
        commit_hash=commit_hash,
        commit_status=commit_status,
        commit_url=commit_url,
        diff_included=False,
        extension_version=deps.extension_version,
        run_label=plan.run_label,
        tags=plan.tags,
        notes=request.metadata.notes,
        execution_summary=summarize_execution(notebook_json),
    )
    bundle = build_snapshot_bundle(
        directory_name=directory_name,
        target=_render_target(
            effective.target,
            deps=deps,
            request=request,
            repo=repo,
            run_label=plan.run_label,
            timestamp=timestamp,
            commit_hash=commit_hash,
        ),
        metadata=metadata,
        notebook=(
            NotebookPayload(
                filename=context.notebook_name,
                content=json.dumps(notebook_json).encode("utf-8"),
            )
            if effective.include_notebook_file
            else None
        ),
        figures=figures,
        files=watched,
    )
    snapshot_context = SnapshotContext(
        job_id=job_id,
        submitted_at=request.client_timestamp or timestamp,
        source=request.source,
        notebook_path=notebook_path,
        run_outcome=run_outcome,
        snapshot_id=snapshot_id,
        commit_hash=commit_hash,
        commit_status=commit_status,
        commit_url=commit_url,
    )
    return execute_snapshot(
        bundle=bundle,
        context=snapshot_context,
        delivery=deps.delivery,
        activity=deps.activity,
        clock=deps.clock,
    )


def _maybe_commit(
    deps: PipelineDependencies,
    request: SnapshotRequest,
    effective: EffectiveConfig,
    repo: RepoContext,
    *,
    timestamp: datetime,
    will_commit: bool,
) -> tuple[CommitHash | None, str]:
    if not will_commit or repo.repo_root is None:
        return repo.head_commit, "reused" if repo.head_commit is not None else "none"
    paths = (
        [RelativeRepoPath(repo.relative_notebook_path)]
        if repo.relative_notebook_path is not None
        else []
    )
    deps.git_mutator.stage(repo.repo_root, paths)
    message = effective.commit_message_template.format(
        notebook_name=request.notebook_context.notebook_name,
        timestamp=timestamp.isoformat(timespec="seconds"),
    )
    new_head = deps.git_mutator.commit(
        repo.repo_root, message=message, current_head=repo.head_commit
    )
    if new_head is not None and new_head != repo.head_commit:
        return new_head, "created"
    return repo.head_commit, "reused" if repo.head_commit is not None else "none"


def _render_target(
    target: LabArchivesTarget,
    *,
    deps: PipelineDependencies,
    request: SnapshotRequest,
    repo: RepoContext,
    run_label: str | None,
    timestamp: datetime,
    commit_hash: str | None,
) -> LabArchivesTarget:
    notebook_name = request.notebook_context.notebook_name
    relative = repo.relative_notebook_path or notebook_name
    variables = {
        "name": target.project_name,
        "project_name": target.project_name,
        "user_id": deps.user_id,
        "user_email": deps.user_email or "unknown-email",
        "repo_name": Path(repo.repo_root).name if repo.repo_root else "no-repo",
        "notebook_name": notebook_name,
        "notebook_stem": Path(notebook_name).stem,
        "relative_notebook_path": relative,
        "scope_path": relative,
        "scope_name": Path(relative).name or relative,
        "run_label": run_label or "unlabeled",
        "experiment_context": "no-context",
        "timestamp": timestamp.isoformat(timespec="seconds").replace(":", "-"),
        "date": timestamp.strftime("%Y-%m-%d"),
        "time": timestamp.strftime("%H-%M-%S"),
        "source": request.source.value,
        "commit_hash": commit_hash or "dirty",
    }
    segments = render_target_path(str(target.root_path), variables)
    return LabArchivesTarget(
        notebook_name=target.notebook_name,
        root_path=LabArchivesRootPath("/".join(segments)),
        project_name=target.project_name,
    )


def _load_repo_config(
    deps: PipelineDependencies, repo_root: str | None
) -> RepoConfig | None:
    if repo_root is None:
        return None
    config_path = Path(repo_root) / _REPO_CONFIG_FILENAME
    if not deps.filesystem.is_file(config_path):
        return None
    text = deps.filesystem.read_bytes(config_path).decode("utf-8")
    return parse_repo_config(text, default_project_name=Path(repo_root).name)


def _load_notebook_json(
    deps: PipelineDependencies, notebook_path: NotebookPath
) -> Mapping[str, object]:
    raw = deps.filesystem.read_bytes(Path(notebook_path))
    return _as_dict(json.loads(raw.decode("utf-8"))) or {}


def _notebook_metadata(request: SnapshotRequest) -> Mapping[str, object]:
    content = request.notebook_content
    if content is None:
        return {}
    metadata = _as_dict(content.get("metadata"))
    if metadata is None:
        return {}
    return _as_dict(metadata.get("save_my_jupyter")) or {}


def _cell_sources(notebook_json: Mapping[str, object]) -> list[str]:
    return [_join_source(cell.get("source")) for cell in _cells(notebook_json)]


def _triggering_cell_source(
    notebook_json: Mapping[str, object], request: SnapshotRequest
) -> str | None:
    triggering = request.notebook_context.triggering_cell_id
    if triggering is None:
        return None
    for cell in _cells(notebook_json):
        if cell.get("id") == triggering:
            return _join_source(cell.get("source"))
    return None


def _cells(notebook_json: Mapping[str, object]) -> list[dict[str, object]]:
    cells = notebook_json.get("cells")
    if not isinstance(cells, list):
        return []
    return [normalized for cell in cells if (normalized := _as_dict(cell)) is not None]


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): nested for key, nested in value.items()}


def _join_source(source: object) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return ""

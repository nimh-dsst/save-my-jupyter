"""The snapshot execution pipeline (target CAPTURE -> DELIVER -> CONFIRM): the
function the worker runs for one job. It resolves config, captures artifacts,
optionally commits, builds the bundle, and delivers it, recording the Activity
row via execute_snapshot. All IO is through injected ports, so it is testable
end-to-end with fakes."""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.application.config import (
    parse_notebook_metadata,
    resolve_effective_config,
)
from save_my_jupyter.application.config.discovery import discover_repo_config
from save_my_jupyter.application.snapshot.build import (
    build_snapshot_bundle,
    format_directory_name,
)
from save_my_jupyter.application.snapshot.capture_reader import gather_watched_files
from save_my_jupyter.application.snapshot.commit_url import build_commit_url
from save_my_jupyter.application.snapshot.diff import (
    DIFF_FILTER_QUALIFIER,
    filter_diff,
)
from save_my_jupyter.application.snapshot.directives import parse_directives
from save_my_jupyter.application.snapshot.execute import (
    SnapshotContext,
    execute_snapshot,
)
from save_my_jupyter.application.snapshot.fingerprint import compute_run_fingerprint
from save_my_jupyter.application.snapshot.guards import (
    NOTEBOOK_MAX_BYTES,
    enforce_size_cap,
)
from save_my_jupyter.application.snapshot.notebook_content import (
    extract_figures,
    outline_notebook,
    summarize_execution,
)
from save_my_jupyter.application.snapshot.notebook_diff import render_notebook_diff
from save_my_jupyter.application.snapshot.plan import plan_capture
from save_my_jupyter.application.snapshot.target_path import render_target_path
from save_my_jupyter.domain.artifacts import NotebookPayload, WatchedFileArtifact
from save_my_jupyter.domain.config import EffectiveConfig, LabArchivesTarget
from save_my_jupyter.domain.delivery import NotebookDiff, SnapshotMetadata
from save_my_jupyter.domain.enums import CommitMode, SnapshotSource
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.jobs import RunOutcome
from save_my_jupyter.domain.types import (
    CommitHash,
    LabArchivesRootPath,
    NotebookPath,
    RelativeRepoPath,
    RunFingerprint,
    SnapshotId,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from save_my_jupyter.domain.activity import ActivityRecord
    from save_my_jupyter.domain.config import RepoConfig, UserSettingsConfig
    from save_my_jupyter.domain.repo import RepoContext
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.ports import (
        ActivityStore,
        Clock,
        Delivery,
        FileSystem,
        GitDiffProvider,
        GitMutator,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineDependencies:
    git_inspector: GitDiffProvider
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

    notebook_json = request.notebook_content or _load_notebook_json(
        deps, context.notebook_path
    )
    repo_config = discover_repo_config(
        filesystem=deps.filesystem,
        notebook_path=context.notebook_path,
        repo_root=repo.repo_root,
    )
    resolved = resolve_effective_config(
        request_commit_mode=request.commit_mode,
        request_watched_paths=request.watched_paths,
        notebook=parse_notebook_metadata(_notebook_metadata(notebook_json)),
        user=deps.user_settings,
        repo=repo_config.config,
    )
    effective = resolved.effective
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
        default_tags=_default_tags(deps.user_settings, repo_config.config),
        default_run_label=deps.user_settings.default_run_label,
        triggering_cell_source=_triggering_cell_source(notebook_json, request),
    )

    notebook_diff = _notebook_diff(deps, repo, notebook_json)
    timestamp = deps.clock.now()
    capture_root = Path(repo.repo_root) if repo.repo_root else repo_config.root
    watched = gather_watched_files(
        watched_paths=effective.watched_paths,
        capture_root=capture_root,
        filesystem=deps.filesystem,
    )
    watched_repo_paths = _watched_relative_repo_paths(watched)
    commit_hash, commit_status = _maybe_commit(
        deps,
        request,
        effective,
        repo,
        timestamp=timestamp,
        will_commit=will_commit,
        watched_paths=watched_repo_paths,
        config_path=repo_config.path,
    )
    snapshot_id = SnapshotId(uuid.uuid4().hex[:12])
    directory_name = format_directory_name(timestamp=timestamp, snapshot_id=snapshot_id)

    run_outcome = _run_outcome(request)
    notebook_path = str(repo.relative_notebook_path or context.notebook_path)
    commit_url = build_commit_url(repo.remote_url, commit_hash)
    notebook_payload = _notebook_payload(context.notebook_name, notebook_json)
    diff_text = _working_tree_diff(
        deps,
        effective,
        repo,
        commit_status=commit_status,
        watched_paths=watched_repo_paths,
    )
    metadata = SnapshotMetadata(
        notebook_name=context.notebook_name,
        notebook_path=notebook_path,
        source=request.source,
        run_outcome=run_outcome,
        snapshot_id=snapshot_id,
        run_fingerprint=_run_fingerprint(request),
        trigger_cells=context.triggered_cell_ids,
        commit_hash=commit_hash,
        commit_status=commit_status,
        commit_url=commit_url,
        diff_included=diff_text is not None or notebook_diff is not None,
        extension_version=deps.extension_version,
        run_label=plan.run_label,
        tags=plan.tags,
        notes=request.metadata.notes,
        execution_summary=summarize_execution(notebook_json),
        extra_fields={**effective.metadata_template, **request.metadata.extra_fields},
        notebook_diff=notebook_diff,
        working_tree_diff=diff_text,
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
        notebook=(notebook_payload if effective.include_notebook_file else None),
        figures=figures,
        files=watched,
        diff_text=diff_text,
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
    watched_paths: Sequence[RelativeRepoPath],
    config_path: Path,
) -> tuple[CommitHash | None, str]:
    if not will_commit or repo.repo_root is None:
        return repo.head_commit, "reused" if repo.head_commit is not None else "none"
    paths: list[RelativeRepoPath] = []
    if effective.stage_notebook_on_commit and repo.relative_notebook_path is not None:
        paths.append(RelativeRepoPath(repo.relative_notebook_path))
    if effective.stage_watched_paths_on_commit:
        paths.extend(watched_paths)
    if deps.filesystem.is_file(config_path):
        with suppress(ValueError):
            paths.append(
                RelativeRepoPath(config_path.relative_to(repo.repo_root).as_posix())
            )
    deps.git_mutator.stage(repo.repo_root, paths)
    if not paths:
        return repo.head_commit, "reused" if repo.head_commit is not None else "none"
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


def _default_tags(
    user_settings: UserSettingsConfig, repo_config: RepoConfig | None
) -> tuple[str, ...]:
    repo_tags = repo_config.default_tags if repo_config is not None else ()
    return (*repo_tags, *user_settings.default_tags)


def _load_notebook_json(
    deps: PipelineDependencies, notebook_path: NotebookPath
) -> Mapping[str, object]:
    path = Path(notebook_path)
    try:
        raw = deps.filesystem.read_bytes(path)
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


def _working_tree_diff(
    deps: PipelineDependencies,
    effective: EffectiveConfig,
    repo: RepoContext,
    *,
    commit_status: str,
    watched_paths: Sequence[RelativeRepoPath],
) -> str | None:
    if (
        repo.repo_root is None
        or not repo.is_dirty
        or not effective.include_diff_when_dirty
        or commit_status == "created"
    ):
        return None
    paths: list[RelativeRepoPath] = []
    if repo.relative_notebook_path is not None:
        paths.append(RelativeRepoPath(repo.relative_notebook_path))
    paths.extend(watched_paths)
    if not paths:
        return None
    try:
        raw_diff = deps.git_inspector.diff_working_tree(repo.repo_root, paths)
    except SnapshotError:
        raise
    except Exception as exc:
        raise SnapshotError(
            "Unable to generate snapshot diff.",
            code="git_diff_failed",
        ) from exc
    filtered = filter_diff(
        raw_diff, notebook_relative_path=str(repo.relative_notebook_path or "")
    )
    if filtered is None:
        return None
    return f"{DIFF_FILTER_QUALIFIER}\n\n{filtered}"


def _notebook_diff(
    deps: PipelineDependencies,
    repo: RepoContext,
    notebook_json: Mapping[str, object],
) -> NotebookDiff | None:
    if repo.repo_root is None or repo.relative_notebook_path is None:
        return None
    head_bytes = deps.git_inspector.read_head_file(
        repo.repo_root, repo.relative_notebook_path
    )
    if head_bytes is None:
        return None
    try:
        head_json = _as_dict(json.loads(head_bytes.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if head_json is None:
        return None
    return render_notebook_diff(head_json, notebook_json)


def _notebook_payload(
    notebook_name: str, notebook_json: Mapping[str, object]
) -> NotebookPayload:
    content = json.dumps(notebook_json).encode("utf-8")
    enforce_size_cap(
        size_bytes=len(content),
        max_bytes=NOTEBOOK_MAX_BYTES,
        code="notebook_artifact_too_large",
        path=Path(notebook_name),
    )
    return NotebookPayload(filename=notebook_name, content=content)


def _run_outcome(request: SnapshotRequest) -> RunOutcome:
    if request.source is SnapshotSource.MANUAL:
        return RunOutcome.NOT_APPLICABLE
    return request.run_outcome or RunOutcome.SUCCESS


def _run_fingerprint(request: SnapshotRequest) -> RunFingerprint:
    context = request.notebook_context
    return compute_run_fingerprint(
        notebook_key=str(context.document_id or context.notebook_path),
        document_id=context.document_id,
        kernel_id=context.kernel_id,
        triggered_cell_ids=list(context.triggered_cell_ids),
        execution_count=context.cell_execution_count,
        tags=request.metadata.tags,
    )


def _notebook_metadata(notebook_json: Mapping[str, object]) -> Mapping[str, object]:
    metadata = _as_dict(notebook_json.get("metadata"))
    if metadata is None:
        return {}
    return _as_dict(metadata.get("save_my_jupyter")) or {}


def _watched_relative_repo_paths(
    watched: tuple[WatchedFileArtifact, ...],
) -> tuple[RelativeRepoPath, ...]:
    return tuple(
        RelativeRepoPath(relative_path)
        for artifact in watched
        if (relative_path := artifact.relative_path) is not None
    )


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

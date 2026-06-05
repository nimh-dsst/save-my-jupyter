"""Composition root: wires the adapters, application use-cases, and worker into
one ServiceContainer the Tornado handlers read from. Lives outside the layered
core (it depends on everything) and is exercised only via the running server."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from save_my_jupyter.adapters.activity_sqlite import SqliteActivityStore
from save_my_jupyter.adapters.clock_system import SystemClock
from save_my_jupyter.adapters.filesystem_local import LocalFileSystem
from save_my_jupyter.adapters.git_dulwich import DulwichGitInspector, DulwichGitMutator
from save_my_jupyter.adapters.labarchives.auth import LabArchivesAuth
from save_my_jupyter.adapters.labarchives.delivery import LabArchivesDelivery
from save_my_jupyter.adapters.labarchives.labapi_client import LabApiClient
from save_my_jupyter.adapters.local_delivery import LocalDelivery
from save_my_jupyter.application.snapshot.admission import SnapshotAdmission
from save_my_jupyter.application.snapshot.coordinator import SnapshotCoordinator
from save_my_jupyter.application.snapshot.pipeline import (
    PipelineDependencies,
    run_snapshot_pipeline,
)
from save_my_jupyter.domain.config import UserSettingsConfig
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.worker.pool import WorkerPool

if TYPE_CHECKING:
    from save_my_jupyter.domain.activity import ActivityRecord
    from save_my_jupyter.domain.requests import SnapshotRequest
    from save_my_jupyter.ports import ActivityStore, Clock, FileSystem, GitInspector


@dataclass(frozen=True, slots=True, kw_only=True)
class ServiceContainer:
    coordinator: SnapshotCoordinator
    activity: ActivityStore
    auth: LabArchivesAuth
    git_inspector: GitInspector
    filesystem: FileSystem
    user_settings: UserSettingsConfig
    clock: Clock
    worker_pool: WorkerPool
    extension_version: str
    demo_mode: bool


def build_services(
    *,
    data_dir: Path,
    snapshots_dir: Path,
    project_root: Path | None = None,
    user_id: str,
    extension_version: str,
    demo_mode: bool = True,
    user_id_aliases: tuple[str, ...] = (),
) -> ServiceContainer:
    clock: Clock = SystemClock()
    filesystem: FileSystem = LocalFileSystem()
    git_inspector = DulwichGitInspector()
    git_mutator = DulwichGitMutator()
    activity = SqliteActivityStore(
        _activity_db_path(data_dir=data_dir, project_root=project_root)
    )
    activity.abandon_inflight()
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    auth = LabArchivesAuth(user_id=user_id, user_id_aliases=user_id_aliases)
    user_settings = UserSettingsConfig()
    pool = WorkerPool()

    def pipeline(job_id: str, request: SnapshotRequest) -> ActivityRecord:
        if not demo_mode:
            auth.ensure_server_credentials()
        session = auth.current_session()
        if demo_mode:
            delivery = LocalDelivery(snapshots_dir)
        elif session is not None:
            delivery = LabArchivesDelivery(LabApiClient(session))
        else:
            raise SnapshotError(
                "LabArchives session expired; sign in again to continue.",
                code="labarchives_session_expired",
                context={"user_id": user_id},
            )
        deps = PipelineDependencies(
            git_inspector=git_inspector,
            git_mutator=git_mutator,
            filesystem=filesystem,
            delivery=delivery,
            activity=activity,
            clock=clock,
            user_settings=user_settings,
            user_email=auth.user_email(),
            user_id=user_id,
            extension_version=extension_version,
        )
        record = run_snapshot_pipeline(job_id, request, deps)
        if record.error_code == "labarchives_session_expired":
            auth.clear_session()
        return record

    coordinator = SnapshotCoordinator(
        admission=SnapshotAdmission(clock),
        activity=activity,
        clock=clock,
        enqueue=pool.submit,
        pipeline=pipeline,
    )
    return ServiceContainer(
        coordinator=coordinator,
        activity=activity,
        auth=auth,
        git_inspector=git_inspector,
        filesystem=filesystem,
        user_settings=user_settings,
        clock=clock,
        worker_pool=pool,
        extension_version=extension_version,
        demo_mode=demo_mode,
    )


def _activity_db_path(*, data_dir: Path, project_root: Path | None) -> Path:
    if project_root is None:
        return data_dir / "activity.sqlite"
    resolved = project_root.resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    name = _safe_project_data_name(resolved.name)
    return data_dir / "projects" / f"{name}-{digest}" / "activity.sqlite"


def _safe_project_data_name(name: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-" for char in name
    ).strip(".-")
    if cleaned == "":
        return "project"
    return cleaned[:48]

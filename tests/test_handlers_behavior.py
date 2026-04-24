from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from save_my_jupyter.domain import (
    CommitMode,
    EffectiveConfig,
    LabArchivesNotebookName,
    LabArchivesRootPath,
    LabArchivesTarget,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    RelativeRepoPath,
    RelativeWatchPath,
    RepoRootPath,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    RunFingerprint,
    SnapshotAccepted,
    SnapshotFailed,
    SnapshotId,
    SnapshotPersisted,
    SnapshotRecord,
    SnapshotRejected,
    SnapshotSource,
    UserId,
    UserMetadata,
)
from save_my_jupyter.errors import LabArchivesWriteError
from save_my_jupyter.handlers import (
    _render_auth_callback_page,
    process_snapshot_request,
)
from save_my_jupyter.services.container import ServiceContainer


@dataclass(slots=True)
class FakeQueue:
    next_plan: ResolvedSnapshotPlan | None
    finished: list[tuple[RunFingerprint, bool]]

    def start_next(self) -> ResolvedSnapshotPlan | None:
        return self.next_plan

    def mark_finished(
        self,
        run_fingerprint: RunFingerprint,
        *,
        record_run: bool,
    ) -> None:
        self.finished.append((run_fingerprint, record_run))


class FakeCoordinator:
    def __init__(
        self,
        *,
        submit_result: SnapshotAccepted | SnapshotRejected,
        queue: FakeQueue,
    ) -> None:
        self._submit_result = submit_result
        self._queue = queue
        self.submitted_plans: list[ResolvedSnapshotPlan] = []

    def submit(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> SnapshotAccepted | SnapshotRejected:
        self.submitted_plans.append(plan)
        return self._submit_result

    def get_or_create_queue(self, _notebook_key: str) -> FakeQueue:
        return self._queue

    def build_notebook_key(self, context: NotebookContext) -> str:
        return str(context.notebook_path)


class FakeSnapshotService:
    def __init__(
        self,
        *,
        plan: ResolvedSnapshotPlan,
        record: SnapshotRecord,
        persistence_result: SnapshotPersisted | SnapshotFailed,
    ) -> None:
        self._plan = plan
        self._record = record
        self._persistence_result = persistence_result
        self.plan_calls: list[object] = []
        self.execute_calls: list[tuple[ResolvedSnapshotPlan, UserId]] = []
        self.persist_calls: list[tuple[SnapshotRecord, UserId]] = []

    def plan_snapshot(
        self,
        snapshot_request: object,
    ) -> ResolvedSnapshotPlan:
        self.plan_calls.append(snapshot_request)
        return self._plan

    def execute_snapshot(
        self,
        plan: ResolvedSnapshotPlan,
        user_id: UserId,
    ) -> SnapshotRecord:
        self.execute_calls.append((plan, user_id))
        return self._record

    def persist_snapshot(
        self,
        record: SnapshotRecord,
        user_id: UserId,
    ) -> SnapshotPersisted | SnapshotFailed:
        self.persist_calls.append((record, user_id))
        return self._persistence_result


def test_process_snapshot_request_executes_and_persists_accepted_snapshot() -> None:
    root = _make_workspace_temp_dir()
    try:
        plan = _snapshot_plan(
            notebook_path=root / "analysis.ipynb",
            repo_root=root,
            watched_paths=(RelativeWatchPath("outputs"),),
            commit_mode=CommitMode.PROMPT,
        )
        record = _snapshot_record(plan, user_id=UserId("user-1"))
        queue = FakeQueue(next_plan=plan, finished=[])
        coordinator = FakeCoordinator(
            submit_result=SnapshotAccepted(job_id="job-1", queue_position=1),
            queue=queue,
        )
        snapshot_service = FakeSnapshotService(
            plan=plan,
            record=record,
            persistence_result=SnapshotPersisted(
                snapshot_id=record.snapshot_id,
                labarchives_page_id="page-1",
            ),
        )
        services = _service_container(
            snapshot_service=snapshot_service,
            snapshot_coordinator=coordinator,
        )

        result = process_snapshot_request(
            services,
            snapshot_request=plan.request,
            user_id=UserId("user-1"),
        )

        assert result.status == "accepted"
        assert snapshot_service.plan_calls == [plan.request]
        assert snapshot_service.execute_calls == [(plan, UserId("user-1"))]
        assert snapshot_service.persist_calls == [(record, UserId("user-1"))]
        assert queue.finished == [(plan.run_fingerprint, True)]
        assert coordinator.submitted_plans == [plan]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_process_snapshot_request_marks_queue_unfinished_on_persist_failure() -> None:
    root = _make_workspace_temp_dir()
    try:
        plan = _snapshot_plan(
            notebook_path=root / "analysis.ipynb",
            repo_root=root,
            watched_paths=(RelativeWatchPath("outputs"),),
        )
        record = _snapshot_record(plan, user_id=UserId("user-1"))
        queue = FakeQueue(next_plan=plan, finished=[])
        coordinator = FakeCoordinator(
            submit_result=SnapshotAccepted(job_id="job-1", queue_position=1),
            queue=queue,
        )
        snapshot_service = FakeSnapshotService(
            plan=plan,
            record=record,
            persistence_result=SnapshotFailed(
                error_code="labarchives_write_failed",
                message="unable to write snapshot",
            ),
        )
        services = _service_container(
            snapshot_service=snapshot_service,
            snapshot_coordinator=coordinator,
        )

        with pytest.raises(LabArchivesWriteError) as exc_info:
            process_snapshot_request(
                services,
                snapshot_request=plan.request,
                user_id=UserId("user-1"),
            )

        assert exc_info.value.code == "labarchives_write_failed"
        assert queue.finished == [(plan.run_fingerprint, False)]
        assert snapshot_service.execute_calls == [(plan, UserId("user-1"))]
        assert snapshot_service.persist_calls == [(record, UserId("user-1"))]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_process_snapshot_request_does_not_execute_rejected_snapshot() -> None:
    root = _make_workspace_temp_dir()
    try:
        plan = _snapshot_plan(
            notebook_path=root / "analysis.ipynb",
            repo_root=root,
            watched_paths=(RelativeWatchPath("outputs"),),
        )
        record = _snapshot_record(plan, user_id=UserId("user-1"))
        queue = FakeQueue(next_plan=plan, finished=[])
        coordinator = FakeCoordinator(
            submit_result=SnapshotRejected(
                reason_code="duplicate_run",
                message="A snapshot already exists for this run.",
            ),
            queue=queue,
        )
        snapshot_service = FakeSnapshotService(
            plan=plan,
            record=record,
            persistence_result=SnapshotPersisted(
                snapshot_id=record.snapshot_id,
                labarchives_page_id="page-1",
            ),
        )
        services = _service_container(
            snapshot_service=snapshot_service,
            snapshot_coordinator=coordinator,
        )

        result = process_snapshot_request(
            services,
            snapshot_request=plan.request,
            user_id=UserId("user-1"),
        )

        assert result.status == "rejected"
        assert snapshot_service.execute_calls == []
        assert snapshot_service.persist_calls == []
        assert queue.finished == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_render_auth_callback_page_notifies_the_main_tab() -> None:
    html = _render_auth_callback_page(
        message="Authenticated as user@example.com <admin>.",
        notification_message=None,
        notification_status="authenticated",
        request_id="request-123",
        title="LabArchives authentication complete",
    )

    assert "save-my-jupyter-auth" in html
    assert "save-my-jupyter.auth-event" in html
    assert '"requestId": "request-123"' in html
    assert '"status": "authenticated"' in html
    assert "Authenticated as user@example.com &lt;admin&gt;." in html


def _snapshot_plan(
    *,
    notebook_path: Path,
    repo_root: Path | None,
    watched_paths: tuple[RelativeWatchPath, ...],
    commit_mode: CommitMode = CommitMode.NEVER,
) -> ResolvedSnapshotPlan:
    notebook_path.parent.mkdir(parents=True, exist_ok=True)
    notebook_path.write_text("{}", encoding="utf-8")
    relative_notebook_path = (
        RelativeRepoPath(
            str(notebook_path.resolve().relative_to(repo_root.resolve())).replace(
                "\\",
                "/",
            )
        )
        if repo_root is not None
        else None
    )
    request = ManualSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=NotebookPath(str(notebook_path)),
            notebook_name=notebook_path.name,
        ),
        commit_mode=commit_mode,
        user_metadata=UserMetadata(tags=("baseline",)),
    )
    return ResolvedSnapshotPlan(
        request=request,
        repo=ResolvedRepoContext(
            repo_root=None if repo_root is None else RepoRootPath(str(repo_root)),
            relative_notebook_path=relative_notebook_path,
            remote_url=None,
            head_commit=None,
            is_dirty=False,
        ),
        path_rule=None,
        effective_config=EffectiveConfig(
            all_cells_trigger=False,
            commit_mode=commit_mode,
            watched_paths=watched_paths,
            include_notebook_file=True,
            include_diff_when_dirty=True,
            target=LabArchivesTarget(
                notebook_name=LabArchivesNotebookName("Snapshots"),
                root_path=LabArchivesRootPath("Runs"),
            ),
            metadata_template={},
            stage_notebook_on_commit=True,
            stage_watched_paths_on_commit=False,
            commit_message_template="snapshot",
        ),
        run_fingerprint=RunFingerprint("run-1"),
    )


def _snapshot_record(
    plan: ResolvedSnapshotPlan,
    *,
    user_id: UserId,
) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=SnapshotId(f"snapshot-{uuid4().hex}"),
        timestamp=datetime(2026, 4, 15, 20, 0, tzinfo=UTC),
        source=SnapshotSource.MANUAL,
        user_id=user_id,
        notebook_context=plan.request.notebook_context,
        repo=plan.repo,
        path_rule_name=None,
        commit_hash=None,
        commit_url=None,
        dirty_diff=None,
        run_fingerprint=plan.run_fingerprint,
        trigger_cell_ids=(),
        executed_cell_ids=(),
        produced_value_summary=None,
        artifacts=(),
        metadata=plan.request.user_metadata,
        labarchives_target=plan.effective_config.target,
        extension_version="0.1.0",
    )


def _make_workspace_temp_dir() -> Path:
    root = Path.cwd() / f"tmp-handlers-{uuid4().hex}"
    root.mkdir(parents=True)
    return root


def _service_container(**kwargs: object) -> ServiceContainer:
    return cast(ServiceContainer, SimpleNamespace(**kwargs))

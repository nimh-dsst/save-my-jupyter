from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from save_my_jupyter.adapters.labarchives import LabArchivesAdapter
from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.domain import (
    CommitHash,
    CommitMode,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    SnapshotId,
    SnapshotPersistenceResult,
    SnapshotRecord,
    SnapshotRequest,
    UserId,
)
from save_my_jupyter.git.service import DefaultGitService
from save_my_jupyter.services.artifacts import DocumentArtifactCollector
from save_my_jupyter.services.auth import AuthServiceImpl
from save_my_jupyter.services.run_fingerprint import RunFingerprintService


class SnapshotService:
    def __init__(
        self,
        *,
        config_service: ConfigService,
        git_service: DefaultGitService,
        artifact_collector: DocumentArtifactCollector,
        auth_service: AuthServiceImpl,
        labarchives_adapter: LabArchivesAdapter,
        run_fingerprint_service: RunFingerprintService,
    ) -> None:
        self._config_service = config_service
        self._git_service = git_service
        self._artifact_collector = artifact_collector
        self._auth_service = auth_service
        self._labarchives_adapter = labarchives_adapter
        self._run_fingerprint_service = run_fingerprint_service

    def plan_snapshot(
        self,
        request: SnapshotRequest,
        *,
        notebook_metadata: Mapping[str, object] | None = None,
        user_settings: Mapping[str, object] | None = None,
    ) -> ResolvedSnapshotPlan:
        repo = self._git_service.resolve_repo(request.notebook_context.notebook_path)
        resolved_config = self._config_service.resolve_effective_config(
            request=request,
            notebook_metadata=notebook_metadata,
            user_settings=user_settings,
        )

        return ResolvedSnapshotPlan(
            request=request,
            repo=repo,
            path_rule=resolved_config.path_rule,
            effective_config=resolved_config.effective_config,
            run_fingerprint=self._run_fingerprint_service.compute(request),
        )

    def execute_snapshot(
        self,
        plan: ResolvedSnapshotPlan,
        user_id: UserId,
    ) -> SnapshotRecord:
        commit_hash = self._resolve_commit_hash(plan)
        resolved_repo = self._resolve_repo_state(plan)
        resolved_plan = replace(plan, repo=resolved_repo)
        remote_url = (
            str(resolved_repo.remote_url)
            if resolved_repo.remote_url is not None
            else None
        )
        commit_url = self._git_service.build_commit_url(
            remote_url,
            commit_hash,
        )
        dirty_diff = None
        if resolved_repo.is_dirty and plan.effective_config.include_diff_when_dirty:
            dirty_diff = self._git_service.generate_diff(resolved_plan)

        artifacts = self._artifact_collector.collect_all(resolved_plan, dirty_diff)
        produced_value_summary = self._artifact_collector.collect_value_summary(
            resolved_plan
        )

        return SnapshotRecord(
            snapshot_id=SnapshotId(uuid4().hex),
            timestamp=datetime.now(UTC),
            source=plan.request.source,
            user_id=user_id,
            notebook_context=plan.request.notebook_context,
            repo=resolved_repo,
            path_rule_name=plan.path_rule.rule_name
            if plan.path_rule is not None
            else None,
            commit_hash=commit_hash,
            commit_url=commit_url,
            dirty_diff=dirty_diff,
            run_fingerprint=plan.run_fingerprint,
            trigger_cell_ids=(
                (plan.request.notebook_context.triggering_cell_id,)
                if plan.request.notebook_context.triggering_cell_id is not None
                else ()
            ),
            executed_cell_ids=plan.request.notebook_context.cell_ids,
            produced_value_summary=produced_value_summary,
            artifacts=artifacts,
            metadata=plan.request.user_metadata,
            labarchives_target=plan.effective_config.target,
            extension_version="0.1.0",
        )

    def persist_snapshot(
        self,
        record: SnapshotRecord,
        user_id: UserId,
    ) -> SnapshotPersistenceResult:
        session = self._auth_service.get_authenticated_user(str(user_id))
        return self._labarchives_adapter.write_snapshot(record, session)

    def _resolve_commit_hash(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> CommitHash | None:
        if plan.repo.repo_root is None:
            return None
        if plan.effective_config.commit_mode is CommitMode.NEVER:
            return None
        return self._git_service.create_commit(plan)

    def _resolve_repo_state(
        self,
        plan: ResolvedSnapshotPlan,
    ) -> ResolvedRepoContext:
        if plan.repo.repo_root is None:
            return plan.repo
        return self._git_service.resolve_repo(
            plan.request.notebook_context.notebook_path
        )

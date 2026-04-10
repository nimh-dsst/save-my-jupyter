from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any, TypeVar, cast

from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join
from tornado import web

from save_my_jupyter.api.parsers import (
    parse_snapshot_request,
    parse_watch_registration_request,
)
from save_my_jupyter.domain import (
    CommitMode,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    ResolvedPathRule,
    ResolvedRepoContext,
    ResolvedSnapshotPlan,
    SnapshotAccepted,
    SnapshotFailed,
    SnapshotRejected,
    SnapshotRequest,
    UserId,
    UserMetadata,
)
from save_my_jupyter.errors import LabArchivesWriteError, SaveMyJupyterError
from save_my_jupyter.services.container import ServiceContainer

_NOTEBOOK_METADATA_KEY = "save_my_jupyter"
HandlerMethod = TypeVar("HandlerMethod", bound=Callable[..., object])
authenticated = cast("Callable[[HandlerMethod], HandlerMethod]", web.authenticated)


class BaseSaveMyJupyterHandler(JupyterHandler):  # type: ignore[misc]
    @property
    def services(self) -> ServiceContainer:
        return cast("ServiceContainer", self.settings["save_my_jupyter_services"])

    def write_json(self, payload: dict[str, Any], *, status: HTTPStatus) -> None:
        self.set_status(status.value)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(payload))


class StateHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def get(self) -> None:
        user_id = _current_user_id(self.current_user)
        auth_status = self.services.auth_service.get_auth_status(str(user_id))
        notebook_path_arg = self.get_query_argument("notebook_path", default="")
        if notebook_path_arg == "":
            self.write_json(
                {
                    "auth": _serialize_auth_status(auth_status),
                    "effectiveConfig": None,
                    "notebookMetadata": None,
                    "pathRule": None,
                    "repo": None,
                    "repoConfigLoaded": False,
                },
                status=HTTPStatus.OK,
            )
            return

        notebook_path = NotebookPath(notebook_path_arg)
        notebook_metadata = _load_notebook_extension_metadata(notebook_path)
        snapshot_request = ManualSnapshotRequest(
            notebook_context=NotebookContext(
                notebook_path=notebook_path,
                notebook_name=Path(notebook_path).name,
            ),
            commit_mode=CommitMode.PROMPT,
            user_metadata=UserMetadata(),
        )
        (
            repo_config,
            resolved_notebook_metadata,
            _user_settings,
            path_rule,
            effective_config,
        ) = self.services.config_service.resolve_effective_config(
            request=snapshot_request,
            user_id=user_id,
            notebook_metadata=notebook_metadata,
        )
        repo = self.services.git_service.resolve_repo(notebook_path)
        self.write_json(
            {
                "auth": _serialize_auth_status(auth_status),
                "effectiveConfig": _serialize_effective_config(effective_config),
                "notebookMetadata": _serialize_notebook_metadata(
                    resolved_notebook_metadata
                ),
                "pathRule": _serialize_path_rule(path_rule),
                "repo": _serialize_repo(repo),
                "repoConfigLoaded": repo_config is not None,
            },
            status=HTTPStatus.OK,
        )


class SnapshotHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        try:
            raw_body = self.get_json_body()
            snapshot_request = parse_snapshot_request(raw_body)
            user_id = _current_user_id(self.current_user)
            result = process_snapshot_request(
                self.services,
                snapshot_request=snapshot_request,
                user_id=user_id,
            )
            self.write_json(
                _serialize_submission_result(result),
                status=HTTPStatus.ACCEPTED,
            )
        except SaveMyJupyterError as exc:
            self.write_json(
                {"error": _serialize_error(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )


class WatchSyncHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        try:
            raw_body = self.get_json_body()
            registration_request = parse_watch_registration_request(raw_body)
            user_id = _current_user_id(self.current_user)
            synthetic_request = ManualSnapshotRequest(
                notebook_context=registration_request.notebook_context,
                commit_mode=registration_request.commit_mode,
                user_metadata=registration_request.user_metadata,
            )
            notebook_metadata = {
                "watched_paths": [
                    str(path) for path in registration_request.watch_paths
                ]
            }
            plan = self.services.snapshot_service.plan_snapshot(
                synthetic_request,
                user_id,
                notebook_metadata=notebook_metadata,
            )
            _sync_watch_registration_from_plan(
                self.services,
                plan=plan,
                user_id=user_id,
            )
            self.write_json(
                {
                    "registeredWatchPaths": [
                        str(path) for path in plan.effective_config.watched_paths
                    ],
                    "status": "registered"
                    if plan.effective_config.watched_paths
                    else "unregistered",
                },
                status=HTTPStatus.OK,
            )
        except SaveMyJupyterError as exc:
            self.write_json(
                {"error": _serialize_error(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )


class AuthStartHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        auth_service = self.services.auth_service
        user_id = str(_current_user_id(self.current_user))
        callback_base_url = (
            f"{self.request.protocol}://{self.request.host}"
            f"{url_path_join(self.base_url, 'save-my-jupyter', 'auth', 'callback')}"
        )
        result = auth_service.start_auth(user_id, callback_base_url)
        self.write_json(
            {
                "authUrl": result.auth_url,
                "message": result.message,
                "requestId": result.request_id,
                "status": result.status,
            },
            status=HTTPStatus.ACCEPTED,
        )


class AuthStatusHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def get(self) -> None:
        auth_service = self.services.auth_service
        user_id = str(_current_user_id(self.current_user))
        payload = _serialize_auth_status(auth_service.get_auth_status(user_id))
        self.write_json(payload, status=HTTPStatus.OK)


class AuthCallbackHandler(BaseSaveMyJupyterHandler):
    def get(self, request_id: str) -> None:
        auth_service = self.services.auth_service
        error = self.get_query_argument("error", default=None)
        self.set_header("Content-Type", "text/html; charset=utf-8")
        if error is not None:
            auth_service.fail_pending_auth(request_id)
            self.finish(
                "<html><body><h1>LabArchives authentication failed</h1>"
                f"<p>{web.xhtml_escape(error)}</p></body></html>"
            )
            return

        try:
            email = self.get_query_argument("email")
            auth_code = self.get_query_argument("auth_code")
            session = auth_service.complete_auth(
                request_id,
                email=email,
                auth_code=auth_code,
            )
            self.finish(
                "<html><body><h1>LabArchives authentication complete</h1>"
                f"<p>Authenticated as {web.xhtml_escape(session.user_email)}.</p>"
                "<p>You can close this tab and return to JupyterLab.</p>"
                "</body></html>"
            )
        except SaveMyJupyterError as exc:
            self.set_status(HTTPStatus.BAD_REQUEST.value)
            self.finish(
                "<html><body><h1>LabArchives authentication failed</h1>"
                f"<p>{web.xhtml_escape(str(exc))}</p></body></html>"
            )


def process_snapshot_request(
    services: ServiceContainer,
    *,
    snapshot_request: SnapshotRequest,
    user_id: UserId,
) -> SnapshotAccepted | SnapshotRejected:
    snapshot_service = services.snapshot_service
    coordinator = services.snapshot_coordinator
    plan = snapshot_service.plan_snapshot(snapshot_request, user_id)
    _sync_watch_registration_from_plan(services, plan=plan, user_id=user_id)
    result = coordinator.submit(plan)
    if isinstance(result, SnapshotAccepted):
        queue = coordinator.get_or_create_queue(
            coordinator.build_notebook_key(snapshot_request.notebook_context)
        )
        next_plan = queue.start_next()
        if next_plan is not None:
            try:
                record = snapshot_service.execute_snapshot(next_plan, user_id)
                persistence_result = snapshot_service.persist_snapshot(record, user_id)
                if isinstance(persistence_result, SnapshotFailed):
                    raise LabArchivesWriteError(
                        persistence_result.message,
                        code=persistence_result.error_code,
                    )
            except SaveMyJupyterError:
                queue.mark_finished(
                    next_plan.run_fingerprint,
                    record_run=False,
                )
                raise
            queue.mark_finished(
                next_plan.run_fingerprint,
                record_run=True,
            )
    return result


def _sync_watch_registration_from_plan(
    services: ServiceContainer,
    *,
    plan: ResolvedSnapshotPlan,
    user_id: UserId,
) -> None:
    notebook_path = plan.request.notebook_context.notebook_path
    if not plan.effective_config.watched_paths:
        services.watch_service.unregister_notebook_watch(notebook_path)
        return

    root = (
        Path(plan.repo.repo_root).resolve()
        if plan.repo.repo_root is not None
        else Path(notebook_path).resolve().parent
    )
    services.watch_service.register_notebook_watch(
        commit_mode=_resolve_automatic_commit_mode(plan.effective_config.commit_mode),
        notebook_context=plan.request.notebook_context,
        root=root,
        user_id=user_id,
        user_metadata=plan.request.user_metadata,
        watch_paths=plan.effective_config.watched_paths,
    )


def _resolve_automatic_commit_mode(commit_mode: CommitMode) -> CommitMode:
    if commit_mode is CommitMode.PROMPT:
        return CommitMode.NEVER
    return commit_mode


def _load_notebook_extension_metadata(
    notebook_path: NotebookPath,
) -> dict[str, object]:
    notebook = Path(notebook_path).resolve()
    try:
        notebook_model = json.loads(notebook.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    metadata = notebook_model.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    extension_metadata = metadata.get(_NOTEBOOK_METADATA_KEY)
    if not isinstance(extension_metadata, dict):
        return {}
    return {str(key): value for key, value in extension_metadata.items()}


def _serialize_auth_status(auth_status: Any) -> dict[str, object]:
    return {
        "pendingRequestId": auth_status.pending_request_id,
        "status": auth_status.status,
        "userEmail": auth_status.user_email,
    }


def _serialize_effective_config(effective_config: Any) -> dict[str, object]:
    return {
        "allCellsTrigger": effective_config.all_cells_trigger,
        "commitMode": effective_config.commit_mode.value,
        "includeDiffWhenDirty": effective_config.include_diff_when_dirty,
        "includeNotebookFile": effective_config.include_notebook_file,
        "metadataTemplate": dict(effective_config.metadata_template),
        "stageNotebookOnCommit": effective_config.stage_notebook_on_commit,
        "stageWatchedPathsOnCommit": effective_config.stage_watched_paths_on_commit,
        "target": {
            "notebookName": effective_config.target.notebook_name,
            "rootPath": effective_config.target.root_path,
        },
        "watchedPaths": [str(path) for path in effective_config.watched_paths],
    }


def _serialize_error(exc: SaveMyJupyterError) -> dict[str, object]:
    return {
        "code": exc.code,
        "context": exc.context,
        "message": str(exc),
    }


def _serialize_notebook_metadata(metadata: Any) -> dict[str, object]:
    return {
        "all_cells_trigger": metadata.trigger_mode.value == "all_cells",
        "default_metadata": dict(metadata.default_metadata),
        "enabled": metadata.enabled,
        "labarchives_target_notebook": metadata.labarchives_target_notebook,
        "labarchives_target_root_path": metadata.labarchives_target_root_path,
        "trigger_cell_ids": [str(cell_id) for cell_id in metadata.trigger_cell_ids],
        "watched_paths": [str(path) for path in metadata.watched_paths],
    }


def _serialize_path_rule(
    path_rule: ResolvedPathRule | None,
) -> dict[str, object] | None:
    if path_rule is None:
        return None
    return {
        "includePaths": [str(path) for path in path_rule.include_paths],
        "metadataTemplate": dict(path_rule.metadata_template),
        "name": path_rule.rule_name,
        "target": None
        if path_rule.target is None
        else {
            "notebookName": path_rule.target.notebook_name,
            "rootPath": path_rule.target.root_path,
        },
        "watchPaths": [str(path) for path in path_rule.watch_paths],
    }


def _serialize_repo(repo: ResolvedRepoContext | None) -> dict[str, object] | None:
    if repo is None:
        return None
    return {
        "headCommit": repo.head_commit,
        "isDirty": repo.is_dirty,
        "relativeNotebookPath": repo.relative_notebook_path,
        "remoteUrl": repo.remote_url,
        "repoHost": repo.repo_host.value,
        "repoRoot": repo.repo_root,
    }


def _serialize_submission_result(
    result: SnapshotAccepted | SnapshotRejected,
) -> dict[str, object]:
    if isinstance(result, SnapshotAccepted):
        return {
            "jobId": result.job_id,
            "queuePosition": result.queue_position,
            "status": result.status,
        }
    return {
        "message": result.message,
        "reasonCode": result.reason_code,
        "status": result.status,
    }


def _current_user_id(current_user: object) -> UserId:
    if isinstance(current_user, bytes):
        return UserId(current_user.decode())
    return UserId(str(current_user))

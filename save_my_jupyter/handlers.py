from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join
from tornado import web

from save_my_jupyter.api.parsers import (
    parse_snapshot_request,
    parse_watch_registration_request,
)
from save_my_jupyter.api.responses import (
    build_empty_state_payload,
    build_state_payload,
    serialize_auth_status,
    serialize_config_init_result,
    serialize_error,
    serialize_submission_result,
)
from save_my_jupyter.api.responses import (
    render_auth_callback_page as _render_auth_callback_page,
)
from save_my_jupyter.domain import (
    CommitMode,
    ManualSnapshotRequest,
    NotebookContext,
    NotebookPath,
    ResolvedSnapshotPlan,
    SnapshotAccepted,
    SnapshotFailed,
    SnapshotRejected,
    SnapshotRequest,
    UserId,
    UserMetadata,
    WatchRegistrationRequest,
)
from save_my_jupyter.errors import LabArchivesWriteError, SaveMyJupyterError
from save_my_jupyter.notebook import load_notebook_extension_metadata
from save_my_jupyter.parsing import expect
from save_my_jupyter.services.auth import AuthStartResult, AuthStatusResult
from save_my_jupyter.services.container import ServiceContainer

authenticated = cast("Any", web.authenticated)


class BaseSaveMyJupyterHandler(JupyterHandler):
    @property
    def services(self) -> ServiceContainer:
        return cast("ServiceContainer", self.settings["save_my_jupyter_services"])

    @property
    def user_id(self) -> UserId:
        return _current_user_id(self.current_user)

    def require_json_body(self) -> dict[str, Any]:
        return _require_json_body(self.get_json_body())

    def write_error_response(
        self,
        exc: SaveMyJupyterError,
        *,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
    ) -> None:
        self.write_json({"error": serialize_error(exc)}, status=status)

    def write_json(self, payload: dict[str, object], *, status: HTTPStatus) -> None:
        self.set_status(status.value)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(payload))


class StateHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def get(self) -> None:
        user_id = self.user_id
        auth_status = self.services.auth_service.get_auth_status(str(user_id))
        notebook_path_arg = self.get_query_argument("notebook_path", default="")
        if notebook_path_arg == "":
            self.write_json(
                build_empty_state_payload(auth_status=auth_status),
                status=HTTPStatus.OK,
            )
            return

        self.write_json(
            _resolve_state_payload(
                self.services,
                auth_status=auth_status,
                notebook_path=NotebookPath(notebook_path_arg),
                user_id=user_id,
            ),
            status=HTTPStatus.OK,
        )


class SnapshotHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        try:
            snapshot_request = parse_snapshot_request(self.require_json_body())
            result = process_snapshot_request(
                self.services,
                snapshot_request=snapshot_request,
                user_id=self.user_id,
            )
        except SaveMyJupyterError as exc:
            self.write_error_response(exc)
            return

        self.write_json(
            serialize_submission_result(result),
            status=HTTPStatus.ACCEPTED,
        )


class WatchSyncHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        try:
            registration_request = parse_watch_registration_request(
                self.require_json_body()
            )
            plan = _plan_watch_registration(
                self.services,
                registration_request=registration_request,
                user_id=self.user_id,
            )
        except SaveMyJupyterError as exc:
            self.write_error_response(exc)
            return

        self.write_json(
            _serialize_watch_sync_result(plan),
            status=HTTPStatus.OK,
        )


class AuthStartHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        try:
            result = self.services.auth_service.start_auth(
                str(self.user_id),
                _build_auth_callback_base_url(self),
            )
        except SaveMyJupyterError as exc:
            self.write_error_response(exc)
            return

        self.write_json(
            _serialize_auth_start_result(result),
            status=HTTPStatus.ACCEPTED,
        )


class AuthStatusHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def get(self) -> None:
        payload = serialize_auth_status(
            self.services.auth_service.get_auth_status(str(self.user_id))
        )
        self.write_json(payload, status=HTTPStatus.OK)


class ConfigInitHandler(BaseSaveMyJupyterHandler):
    @authenticated
    def post(self) -> None:
        try:
            notebook_path = _require_notebook_path(self.require_json_body())
            repo = self.services.git_service.resolve_repo(notebook_path)
            result = self.services.config_service.ensure_repo_config(
                notebook_path=notebook_path,
                repo_root=_repo_root_path(repo.repo_root),
            )
        except SaveMyJupyterError as exc:
            self.write_error_response(exc)
            return

        self.write_json(
            serialize_config_init_result(result),
            status=HTTPStatus.CREATED if result.status == "created" else HTTPStatus.OK,
        )


class AuthCallbackHandler(BaseSaveMyJupyterHandler):
    def get(self, request_id: str) -> None:
        auth_service = self.services.auth_service
        error = self.get_query_argument("error", default=None)
        self.set_header("Content-Type", "text/html; charset=utf-8")
        if error is not None:
            auth_service.fail_pending_auth(request_id)
            self.finish(
                _render_auth_callback_page(
                    message=error,
                    notification_message=error,
                    notification_status="error",
                    request_id=request_id,
                    title="LabArchives authentication failed",
                )
            )
            return

        try:
            session = auth_service.complete_auth(
                request_id,
                email=self.get_query_argument("email"),
                auth_code=self.get_query_argument("auth_code"),
            )
        except SaveMyJupyterError as exc:
            self.set_status(HTTPStatus.BAD_REQUEST.value)
            self.finish(
                _render_auth_callback_page(
                    message=str(exc),
                    notification_message=str(exc),
                    notification_status="error",
                    request_id=request_id,
                    title="LabArchives authentication failed",
                )
            )
            return

        self.finish(
            _render_auth_callback_page(
                message=f"Authenticated as {session.user_email}.",
                notification_message=None,
                notification_status="authenticated",
                request_id=request_id,
                title="LabArchives authentication complete",
            )
        )


def process_snapshot_request(
    services: ServiceContainer,
    *,
    snapshot_request: SnapshotRequest,
    user_id: UserId,
) -> SnapshotAccepted | SnapshotRejected:
    plan = services.snapshot_service.plan_snapshot(snapshot_request, user_id)

    result = services.snapshot_coordinator.submit(plan)
    if isinstance(result, SnapshotRejected):
        return result

    _execute_next_snapshot(
        services,
        notebook_context=snapshot_request.notebook_context,
        user_id=user_id,
    )
    return result


def _resolve_state_payload(
    services: ServiceContainer,
    *,
    auth_status: AuthStatusResult,
    notebook_path: NotebookPath,
    user_id: UserId,
) -> dict[str, object]:
    snapshot_request = _build_state_snapshot_request(notebook_path)
    notebook_metadata = load_notebook_extension_metadata(notebook_path)
    (
        repo_config,
        resolved_notebook_metadata,
        _resolved_user_settings,
        path_rule,
        effective_config,
    ) = services.config_service.resolve_effective_config(
        request=snapshot_request,
        user_id=user_id,
        notebook_metadata=notebook_metadata,
    )
    repo = services.git_service.resolve_repo(notebook_path)
    repo_config_path = services.config_service.suggested_repo_config_path(
        notebook_path=notebook_path,
        repo_root=_repo_root_path(repo.repo_root),
    )
    return build_state_payload(
        auth_status=auth_status,
        effective_config=effective_config,
        notebook_metadata=resolved_notebook_metadata,
        path_rule=path_rule,
        repo=repo,
        repo_config_loaded=repo_config is not None,
        repo_config_path=repo_config_path,
    )


def _build_state_snapshot_request(notebook_path: NotebookPath) -> ManualSnapshotRequest:
    return ManualSnapshotRequest(
        notebook_context=NotebookContext(
            notebook_path=notebook_path,
            notebook_name=Path(notebook_path).name,
        ),
        commit_mode=CommitMode.PROMPT,
        user_metadata=UserMetadata(),
    )


def _plan_watch_registration(
    services: ServiceContainer,
    *,
    registration_request: WatchRegistrationRequest,
    user_id: UserId,
) -> ResolvedSnapshotPlan:
    return services.snapshot_service.plan_snapshot(
        ManualSnapshotRequest(
            notebook_context=registration_request.notebook_context,
            commit_mode=registration_request.commit_mode,
            user_metadata=registration_request.user_metadata,
        ),
        user_id,
        notebook_metadata={
            "watched_paths": [str(path) for path in registration_request.watch_paths]
        },
    )


def _serialize_watch_sync_result(plan: ResolvedSnapshotPlan) -> dict[str, object]:
    registered_watch_paths = [str(path) for path in plan.effective_config.watched_paths]
    return {
        "registeredWatchPaths": registered_watch_paths,
        "status": "registered" if registered_watch_paths else "unregistered",
    }


def _serialize_auth_start_result(result: AuthStartResult) -> dict[str, object]:
    return {
        "authUrl": result.auth_url,
        "message": result.message,
        "requestId": result.request_id,
        "status": result.status,
    }


def _build_auth_callback_base_url(handler: BaseSaveMyJupyterHandler) -> str:
    return (
        f"{handler.request.protocol}://{handler.request.host}"
        f"{url_path_join(handler.base_url, 'save-my-jupyter', 'auth', 'callback')}"
    )


def _execute_next_snapshot(
    services: ServiceContainer,
    *,
    notebook_context: NotebookContext,
    user_id: UserId,
) -> None:
    coordinator = services.snapshot_coordinator
    queue = coordinator.get_or_create_queue(
        coordinator.build_notebook_key(notebook_context)
    )
    next_plan = queue.start_next()
    if next_plan is None:
        return

    try:
        _persist_planned_snapshot(services, plan=next_plan, user_id=user_id)
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


def _persist_planned_snapshot(
    services: ServiceContainer,
    *,
    plan: ResolvedSnapshotPlan,
    user_id: UserId,
) -> None:
    record = services.snapshot_service.execute_snapshot(plan, user_id)
    persistence_result = services.snapshot_service.persist_snapshot(record, user_id)
    if isinstance(persistence_result, SnapshotFailed):
        raise LabArchivesWriteError(
            persistence_result.message,
            code=persistence_result.error_code,
        )


def _repo_root_path(repo_root: str | None) -> Path | None:
    if repo_root is None:
        return None
    return Path(repo_root)


def _require_notebook_path(raw_body: dict[str, Any]) -> NotebookPath:
    return NotebookPath(
        expect(raw_body.get("notebook_path"), str, field="notebook_path")
    )


def _current_user_id(current_user: object) -> UserId:
    if isinstance(current_user, bytes):
        return UserId(current_user.decode())
    return UserId(str(current_user))


def _require_json_body(raw_body: dict[str, Any] | None) -> dict[str, Any]:
    if raw_body is None:
        raise SaveMyJupyterError(
            "Request body must be valid JSON.",
            code="missing_json_body",
        )
    return raw_body

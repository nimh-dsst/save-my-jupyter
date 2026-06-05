"""Tornado handlers for /save-my-jupyter/* (target transport). Thin: parse the
body, call a service, serialize the result. No business logic. Smoke-only --
exercised through the running server, not the unit suite.

The OAuth sign-in (start + public callback) drives the real LabArchives flow;
it needs server credentials + an account, so it is verified by smoke test."""

from __future__ import annotations

import html
import json
import uuid
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import Any, cast

from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join
from tornado import web

from save_my_jupyter.application.config.starter import (
    StarterConfigInspection,
    StarterConfigResult,
    ensure_starter_config,
    inspect_starter_config,
)
from save_my_jupyter.application.preview import PreviewResult, build_preview
from save_my_jupyter.container import ServiceContainer
from save_my_jupyter.domain.auth import AuthStartResult, AuthStatusResult
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.queue import Rejected
from save_my_jupyter.transport.parsers import (
    ACTIVITY_LIMIT_DEFAULT,
    parse_activity_limit,
    parse_snapshot_request,
)
from save_my_jupyter.transport.responses import (
    serialize_activity,
    serialize_activity_list,
    serialize_error,
    serialize_preview,
    serialize_submission,
)

authenticated = cast("Any", web.authenticated)

_SETTINGS_KEY = "save_my_jupyter_services"
_ROOT_SETTINGS_KEY = "save_my_jupyter_root_dir"
_AUTH_CALLBACK_CLOSE_DELAY_MS = 150
_NOTEBOOK_PATH_REQUIRED_MESSAGE = "notebook_path is required."
_INVALID_NOTEBOOK_PATH_CODE = "invalid_notebook_path"
_WATCH_SYNC_REMOVED_MESSAGE = "Watched paths now travel in the snapshot request."
_WATCH_SYNC_REMOVED_CODE = "watch_sync_removed"


class _BaseHandler(JupyterHandler):
    @property
    def services(self) -> ServiceContainer:
        return cast("ServiceContainer", self.settings[_SETTINGS_KEY])

    @property
    def server_root(self) -> Path:
        return Path(cast("str", self.settings[_ROOT_SETTINGS_KEY]))

    def _write_json(
        self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        self.set_status(status.value)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(payload))

    def _write_error(
        self, exc: SnapshotError, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST
    ) -> None:
        self._log_request_error(exc, status=status)
        self._write_json(serialize_error(exc), status=status)

    def _log_request_error(
        self, exc: SnapshotError, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST
    ) -> None:
        self.log.warning(
            "Save My Jupyter request failed: method=%s uri=%s status=%s "
            "code=%s message=%s context=%s",
            self.request.method,
            self.request.uri,
            status.value,
            exc.code,
            str(exc),
            json.dumps(exc.context, sort_keys=True),
        )

    def _required_notebook_path_query(self) -> str:
        notebook_path = self.get_query_argument("notebook_path", default=None)
        if notebook_path is None:
            raise SnapshotError(
                _NOTEBOOK_PATH_REQUIRED_MESSAGE,
                code=_INVALID_NOTEBOOK_PATH_CODE,
            )
        return notebook_path


class SnapshotHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        if not self.services.auth.is_authenticated():
            self._write_json(
                serialize_submission(
                    Rejected(
                        reason_code="authentication_required",
                        message="Connect LabArchives before creating a snapshot.",
                    )
                )
            )
            return
        try:
            request = parse_snapshot_request(self.get_json_body())
        except SnapshotError as exc:
            self._write_error(exc)
            return
        try:
            decision = self.services.coordinator.submit(
                job_id=uuid.uuid4().hex, request=request
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_json(serialize_submission(decision))


class SnapshotJobsHandler(_BaseHandler):
    @authenticated
    async def get(self, job_id: str | None = None) -> None:
        if job_id:
            record = self.services.activity.get(job_id)
            if record is None:
                self._write_error(
                    SnapshotError(
                        "No such snapshot job.",
                        code="unknown_job",
                        context={"job_id": job_id},
                    ),
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._write_json(serialize_activity(record))
            return
        try:
            limit = parse_activity_limit(
                self.get_query_argument("limit", str(ACTIVITY_LIMIT_DEFAULT))
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_json(serialize_activity_list(self.services.activity.recent(limit)))


class SnapshotPreviewHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        try:
            request = parse_snapshot_request(self.get_json_body())
        except SnapshotError as exc:
            self._write_error(exc)
            return
        try:
            result = build_preview(
                request,
                git_inspector=self.services.git_inspector,
                filesystem=self.services.filesystem,
                user_settings=self.services.user_settings,
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_preview_result(result)

    @authenticated
    async def get(self) -> None:
        try:
            notebook_path = self._required_notebook_path_query()
        except SnapshotError as exc:
            self._write_error(exc)
            return
        try:
            request = parse_snapshot_request(
                {
                    "source": "manual",
                    "notebook_context": {
                        "notebook_path": notebook_path,
                        "notebook_name": PurePosixPath(
                            notebook_path.replace("\\", "/")
                        ).name,
                    },
                }
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        try:
            result = build_preview(
                request,
                git_inspector=self.services.git_inspector,
                filesystem=self.services.filesystem,
                user_settings=self.services.user_settings,
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_preview_result(result)

    def _write_preview_result(self, result: PreviewResult) -> None:
        self._write_json(
            serialize_preview(
                plan=result.plan,
                provenance=result.provenance,
                effective=result.effective,
                repo=result.repo,
                repo_config_path=result.repo_config_path,
                repo_config_loaded=result.repo_config_loaded,
                notes=result.notes,
                extra_fields=result.extra_fields,
                generated_at=self.services.clock.now(),
                source=result.source,
            )
        )


class WatchSyncHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        # Deprecated: watched paths now travel in the snapshot body (C-API-04).
        self._write_json(
            serialize_error(
                SnapshotError(
                    _WATCH_SYNC_REMOVED_MESSAGE,
                    code=_WATCH_SYNC_REMOVED_CODE,
                )
            ),
            status=HTTPStatus.GONE,
        )


class ConfigInitHandler(_BaseHandler):
    @authenticated
    async def get(self) -> None:
        try:
            notebook_path = self._required_notebook_path_query()
        except SnapshotError as exc:
            self._write_error(exc)
            return
        try:
            inspection = inspect_starter_config(
                server_root=self.server_root,
                notebook_path=notebook_path,
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_json(_serialize_config_inspection(inspection))

    @authenticated
    async def post(self) -> None:
        try:
            notebook_path = _config_notebook_path(self.get_json_body())
            result = ensure_starter_config(
                server_root=self.server_root,
                notebook_path=notebook_path,
            )
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_json(_serialize_config_result(result))


class AuthStatusHandler(_BaseHandler):
    @authenticated
    async def get(self) -> None:
        self._write_json(_serialize_auth_status(self.services.auth.status()))


class AuthStartHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        if self.services.demo_mode:
            self.services.auth.connect_demo()
            self._write_json(
                _serialize_auth_start(
                    AuthStartResult(
                        status="authenticated", message="Connected in demo mode."
                    )
                )
            )
            return
        try:
            result = self.services.auth.start(self._callback_base_url())
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_json(_serialize_auth_start(result))

    def _callback_base_url(self) -> str:
        host = f"{self.request.protocol}://{self.request.host}"
        path = url_path_join(self.base_url, "save-my-jupyter", "auth", "callback")
        return f"{host}{path}"


class AuthCallbackHandler(_BaseHandler):
    # Public (no @authenticated): LabArchives redirects the browser here
    # (contract C-API-01, C-API-03).
    async def get(self, request_id: str) -> None:
        error = self.get_query_argument("error", default=None)
        if error is not None:
            try:
                self.services.auth.fail_pending(request_id)
            except SnapshotError as exc:
                self._log_request_error(exc)
                self._render_callback(success=False, message=f"[{exc.code}] {exc}")
                return
            self._render_callback(success=False, message=error)
            return
        email = self.get_query_argument("email", default="")
        auth_code = self.get_query_argument("auth_code", default="")
        try:
            self.services.auth.complete(request_id, email=email, auth_code=auth_code)
        except SnapshotError as exc:
            self._log_request_error(exc)
            self._render_callback(success=False, message=f"[{exc.code}] {exc}")
            return
        self._render_callback(success=True, message=f"Connected as {email}.")

    def _render_callback(self, *, success: bool, message: str) -> None:
        self.set_header("Content-Type", "text/html")
        self.finish(_render_callback_page(success=success, message=message))


class AuthLogoutHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        try:
            self.services.auth.logout()
        except SnapshotError as exc:
            self._write_error(exc)
            return
        self._write_json({"status": "signed_out"})


def _serialize_auth_status(status: AuthStatusResult) -> dict[str, object]:
    return {
        "status": status.status,
        "userEmail": status.user_email,
        "storedUserEmail": status.stored_user_email,
        "pendingRequestId": status.pending_request_id,
        "storedNotebookNames": list(status.stored_notebook_names),
    }


def _serialize_auth_start(result: AuthStartResult) -> dict[str, object]:
    return {
        "status": result.status,
        "message": result.message,
        "authUrl": result.auth_url,
        "requestId": result.request_id,
    }


def _serialize_config_inspection(
    inspection: StarterConfigInspection,
) -> dict[str, object]:
    return {
        "configPath": inspection.config_path,
        "exists": inspection.exists,
        "rootDirectory": inspection.root_directory,
    }


def _serialize_config_result(result: StarterConfigResult) -> dict[str, object]:
    return {
        "configPath": result.config_path,
        "message": result.message,
        "rootDirectory": result.root_directory,
        "status": result.status,
    }


def _config_notebook_path(body: object) -> str:
    if not isinstance(body, Mapping):
        raise SnapshotError(
            "Request body must be a JSON object.", code="missing_json_body"
        )
    mapping = cast("Mapping[str, object]", body)
    value = mapping.get("notebookPath")
    if value is None:
        value = mapping.get("notebook_path")
    if isinstance(value, str):
        return value
    raise SnapshotError(
        "notebookPath must be a string.",
        code="invalid_notebook_path",
    )


def _render_callback_page(*, success: bool, message: str) -> str:
    title = (
        "LabArchives authentication complete"
        if success
        else "LabArchives authentication failed"
    )
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{safe_title}</title></head><body>"
        f"<h1>{safe_title}</h1><p>{safe_message}</p>"
        "<p>You can close this tab and return to JupyterLab.</p>"
        "<script>"
        "try{const c=new BroadcastChannel('save-my-jupyter-auth');"
        "c.postMessage('changed');c.close();}catch(e){}"
        "try{localStorage.setItem('save-my-jupyter-auth',String(Date.now()));}"
        "catch(e){}"
        f"setTimeout(function(){{window.close();}},{_AUTH_CALLBACK_CLOSE_DELAY_MS});"
        "</script></body></html>"
    )

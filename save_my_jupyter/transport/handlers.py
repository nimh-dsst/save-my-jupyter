"""Tornado handlers for /save-my-jupyter/* (target transport). Thin: parse the
body, call a service, serialize the result. No business logic. Smoke-only --
exercised through the running server, not the unit suite.

The OAuth sign-in (start + public callback) drives the real LabArchives flow;
it needs server credentials + an account, so it is verified by smoke test."""

from __future__ import annotations

import html
import json
import uuid
from http import HTTPStatus
from typing import Any, cast

from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join
from tornado import web

from save_my_jupyter.adapters.labarchives.auth import AuthStartResult, AuthStatusResult
from save_my_jupyter.application.preview import build_preview
from save_my_jupyter.container import ServiceContainer
from save_my_jupyter.domain.errors import SnapshotError
from save_my_jupyter.domain.queue import Rejected
from save_my_jupyter.transport.parsers import parse_snapshot_request
from save_my_jupyter.transport.responses import (
    serialize_activity,
    serialize_activity_list,
    serialize_error,
    serialize_preview,
    serialize_submission,
)

authenticated = cast("Any", web.authenticated)

_SETTINGS_KEY = "save_my_jupyter_services"


class _BaseHandler(JupyterHandler):
    @property
    def services(self) -> ServiceContainer:
        return cast("ServiceContainer", self.settings[_SETTINGS_KEY])

    def _write_json(
        self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        self.set_status(status.value)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(payload))

    def _write_error(
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
        self._write_json(serialize_error(exc), status=status)


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
        decision = self.services.coordinator.submit(
            job_id=uuid.uuid4().hex, request=request
        )
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
        limit = int(self.get_query_argument("limit", "20"))
        self._write_json(serialize_activity_list(self.services.activity.recent(limit)))


class SnapshotPreviewHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        try:
            request = parse_snapshot_request(self.get_json_body())
        except SnapshotError as exc:
            self._write_error(exc)
            return
        result = build_preview(
            request,
            git_inspector=self.services.git_inspector,
            filesystem=self.services.filesystem,
            user_settings=self.services.user_settings,
        )
        self._write_json(
            serialize_preview(
                plan=result.plan,
                provenance=result.provenance,
                generated_at=self.services.clock.now(),
                source=result.source,
            )
        )


class WatchSyncHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        # Deprecated: watched paths now travel in the snapshot body (C-API-04).
        self._write_json(
            {
                "error": {
                    "code": "watch_sync_removed",
                    "message": "Watched paths now travel in the snapshot request.",
                    "context": {},
                }
            },
            status=HTTPStatus.GONE,
        )


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
            self.services.auth.fail_pending(request_id)
            self._render_callback(success=False, message=error)
            return
        email = self.get_query_argument("email", default="")
        auth_code = self.get_query_argument("auth_code", default="")
        try:
            self.services.auth.complete(request_id, email=email, auth_code=auth_code)
        except SnapshotError as exc:
            self._render_callback(success=False, message=str(exc))
            return
        self._render_callback(success=True, message=f"Connected as {email}.")

    def _render_callback(self, *, success: bool, message: str) -> None:
        self.set_header("Content-Type", "text/html")
        self.finish(_render_callback_page(success=success, message=message))


class AuthLogoutHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        self.services.auth.logout()
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
        "setTimeout(function(){window.close();},150);"
        "</script></body></html>"
    )

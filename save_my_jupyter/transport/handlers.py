"""Tornado handlers for /save-my-jupyter/* (target transport). Thin: parse the
body, call a service, serialize the result. No business logic. Smoke-only --
exercised through the running server, not the unit suite.

OAuth sign-in (start/callback) is the gate-unverifiable seam (it needs the
labapi handshake + a real LabArchives account); those routes return a clear
error until wired in a smoke test."""

from __future__ import annotations

import json
import uuid
from http import HTTPStatus
from typing import Any, cast

from jupyter_server.base.handlers import JupyterHandler
from tornado import web

from save_my_jupyter.adapters.labarchives.auth import AuthStatus
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


class AuthLogoutHandler(_BaseHandler):
    @authenticated
    async def post(self) -> None:
        self.services.auth.logout()
        self._write_json({"status": "signed_out"})


def _serialize_auth_status(status: AuthStatus) -> dict[str, object]:
    return {
        "status": "authenticated" if status.authenticated else "unauthenticated",
        "userEmail": status.user_email,
        "storedUserEmail": status.stored_user_email,
        "pendingRequestId": status.pending_request_id,
        "storedNotebookNames": list(status.stored_notebook_names),
    }

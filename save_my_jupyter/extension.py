"""Jupyter Server extension composition root. Builds the ServiceContainer, marks
any jobs left in-flight by a prior shutdown as abandoned (C-QUEUE-05), registers
the /save-my-jupyter/* handlers, and shuts the worker pool down cleanly. Smoke-
only -- exercised through a running Jupyter server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from jupyter_core.paths import jupyter_data_dir
from jupyter_server.extension.application import ExtensionApp
from jupyter_server.utils import url_path_join

from save_my_jupyter import __version__
from save_my_jupyter.container import build_services
from save_my_jupyter.transport.handlers import (
    AuthCallbackHandler,
    AuthLogoutHandler,
    AuthStartHandler,
    AuthStatusHandler,
    ConfigInitHandler,
    SnapshotHandler,
    SnapshotJobsHandler,
    SnapshotPreviewHandler,
    WatchSyncHandler,
)

_DATA_SUBDIR = "save_my_jupyter"
_SNAPSHOTS_SUBDIR = "save-my-jupyter-snapshots"


class SaveMyJupyterApp(ExtensionApp):
    extension_name = "save_my_jupyter"

    def initialize_settings(self) -> None:
        super().initialize_settings()  # type: ignore[no-untyped-call]
        data_dir = Path(jupyter_data_dir()) / _DATA_SUBDIR
        data_dir.mkdir(parents=True, exist_ok=True)
        user_id = _current_user_id(self)
        services = build_services(
            data_dir=data_dir,
            snapshots_dir=self._snapshots_dir(),
            user_id=user_id,
            user_id_aliases=_legacy_user_id_aliases(user_id),
            extension_version=__version__,
            demo_mode=_demo_mode_enabled(),
        )
        self.settings["save_my_jupyter_services"] = services
        self.settings["save_my_jupyter_root_dir"] = str(self._server_root())

    def _snapshots_dir(self) -> Path:
        return self._server_root() / _SNAPSHOTS_SUBDIR

    def _server_root(self) -> Path:
        server_app = self.serverapp
        root = server_app.root_dir if server_app is not None else "."
        return Path(root)

    def initialize_handlers(self) -> None:
        server_app = self.serverapp
        assert server_app is not None
        base = server_app.base_url

        def route(*parts: str) -> str:
            return url_path_join(base, "save-my-jupyter", *parts)

        handlers: list[tuple[str, type[Any]]] = [
            (route("snapshot"), SnapshotHandler),
            (route("snapshot-jobs"), SnapshotJobsHandler),
            (route("snapshot-jobs", r"(?P<job_id>[^/]+)"), SnapshotJobsHandler),
            (route("snapshot-preview"), SnapshotPreviewHandler),
            (route("watch", "sync"), WatchSyncHandler),
            (route("config", "init"), ConfigInitHandler),
            (route("auth", "status"), AuthStatusHandler),
            (route("auth", "start"), AuthStartHandler),
            (route("auth", "callback", r"(?P<request_id>[^/]+)"), AuthCallbackHandler),
            (route("auth", "logout"), AuthLogoutHandler),
        ]
        self.handlers.extend(handlers)  # type: ignore[attr-defined]

    async def stop_extension(self) -> None:
        services = self.settings.get("save_my_jupyter_services")
        if services is not None:
            cast("Any", services).worker_pool.shutdown()


def _demo_mode_enabled() -> bool:
    value = os.environ.get("SAVE_MY_JUPYTER_DEMO_MODE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _current_user_id(app: ExtensionApp) -> str:
    server_app = app.serverapp
    if server_app is None:
        return "anonymous"
    identity = getattr(server_app, "identity_provider", None)
    user = getattr(identity, "username", None)
    return str(user) if user else "anonymous"


def _legacy_user_id_aliases(user_id: str) -> tuple[str, ...]:
    if user_id == "anonymous":
        return ()
    return ("anonymous",)


def launch_instance() -> None:
    SaveMyJupyterApp.launch_instance()

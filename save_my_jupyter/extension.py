from __future__ import annotations

from jupyter_server.extension.application import ExtensionApp
from jupyter_server.utils import url_path_join

from save_my_jupyter.adapters.labarchives import LabArchivesAdapter
from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.git.service import DefaultGitService
from save_my_jupyter.handlers import (
    AuthCallbackHandler,
    AuthStartHandler,
    AuthStatusHandler,
    ConfigInitHandler,
    SnapshotHandler,
    StateHandler,
    WatchSyncHandler,
)
from save_my_jupyter.services.artifacts import DocumentArtifactCollector
from save_my_jupyter.services.auth import AuthServiceImpl
from save_my_jupyter.services.container import ServiceContainer
from save_my_jupyter.services.coordinator import SnapshotCoordinator
from save_my_jupyter.services.run_fingerprint import RunFingerprintService
from save_my_jupyter.services.snapshot import SnapshotService


class SaveMyJupyterApp(ExtensionApp):
    extension_name = "save_my_jupyter"

    def initialize_settings(self) -> None:
        super().initialize_settings()  # type: ignore[no-untyped-call]
        config_service = ConfigService()
        git_service = DefaultGitService()
        auth_service = AuthServiceImpl()
        artifact_collector = DocumentArtifactCollector()
        run_fingerprint_service = RunFingerprintService()
        labarchives_adapter = LabArchivesAdapter()
        snapshot_service = SnapshotService(
            config_service=config_service,
            git_service=git_service,
            artifact_collector=artifact_collector,
            auth_service=auth_service,
            labarchives_adapter=labarchives_adapter,
            run_fingerprint_service=run_fingerprint_service,
        )

        services = ServiceContainer(
            artifact_collector=artifact_collector,
            auth_service=auth_service,
            config_service=config_service,
            git_service=git_service,
            run_fingerprint_service=run_fingerprint_service,
            snapshot_coordinator=SnapshotCoordinator(),
            snapshot_service=snapshot_service,
        )
        self.settings["save_my_jupyter_services"] = services

    def initialize_handlers(self) -> None:
        server_app = self.serverapp
        assert server_app is not None
        handlers = [
            (
                url_path_join(server_app.base_url, "save-my-jupyter", "state"),
                StateHandler,
            ),
            (
                url_path_join(server_app.base_url, "save-my-jupyter", "snapshot"),
                SnapshotHandler,
            ),
            (
                url_path_join(
                    server_app.base_url,
                    "save-my-jupyter",
                    "watch",
                    "sync",
                ),
                WatchSyncHandler,
            ),
            (
                url_path_join(server_app.base_url, "save-my-jupyter", "auth", "start"),
                AuthStartHandler,
            ),
            (
                url_path_join(server_app.base_url, "save-my-jupyter", "auth", "status"),
                AuthStatusHandler,
            ),
            (
                url_path_join(server_app.base_url, "save-my-jupyter", "config", "init"),
                ConfigInitHandler,
            ),
            (
                url_path_join(
                    server_app.base_url, "save-my-jupyter", "auth", "callback"
                )
                + "/(?P<request_id>[^/]+)",
                AuthCallbackHandler,
            ),
        ]
        self.handlers.extend(handlers)


def launch_instance() -> None:
    SaveMyJupyterApp.launch_instance()  # type: ignore[no-untyped-call]

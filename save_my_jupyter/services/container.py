from __future__ import annotations

from dataclasses import dataclass

from save_my_jupyter.config.service import ConfigService
from save_my_jupyter.git.service import DefaultGitService
from save_my_jupyter.services.artifacts import DocumentArtifactCollector
from save_my_jupyter.services.auth import AuthServiceImpl
from save_my_jupyter.services.coordinator import SnapshotCoordinator
from save_my_jupyter.services.run_fingerprint import RunFingerprintService
from save_my_jupyter.services.snapshot import SnapshotService


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    artifact_collector: DocumentArtifactCollector
    auth_service: AuthServiceImpl
    config_service: ConfigService
    git_service: DefaultGitService
    run_fingerprint_service: RunFingerprintService
    snapshot_coordinator: SnapshotCoordinator
    snapshot_service: SnapshotService

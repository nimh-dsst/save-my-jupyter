from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorContext:
    details: Mapping[str, str]


class SaveMyJupyterError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        context: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


class SnapshotParseError(SaveMyJupyterError):
    pass


class ConfigParseError(SaveMyJupyterError):
    pass


class ConfigValidationError(SaveMyJupyterError):
    pass


class NotebookMetadataError(SaveMyJupyterError):
    pass


class PathNormalizationError(SaveMyJupyterError):
    pass


class RunFingerprintError(SaveMyJupyterError):
    pass


class GitResolutionError(SaveMyJupyterError):
    pass


class CommitCreationError(SaveMyJupyterError):
    pass


class ArtifactCollectionError(SaveMyJupyterError):
    pass


class LabArchivesWriteError(SaveMyJupyterError):
    pass

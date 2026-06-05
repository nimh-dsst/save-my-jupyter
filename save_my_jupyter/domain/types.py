from __future__ import annotations

from collections.abc import Mapping
from typing import NewType, TypeAlias

UserId = NewType("UserId", str)
NotebookPath = NewType("NotebookPath", str)
RepoRootPath = NewType("RepoRootPath", str)
RelativeRepoPath = NewType("RelativeRepoPath", str)
RelativeWatchPath = NewType("RelativeWatchPath", str)
DocumentId = NewType("DocumentId", str)
KernelId = NewType("KernelId", str)
CellId = NewType("CellId", str)
SnapshotId = NewType("SnapshotId", str)
RunFingerprint = NewType("RunFingerprint", str)
CommitHash = NewType("CommitHash", str)
RemoteUrl = NewType("RemoteUrl", str)
LabArchivesNotebookName = NewType("LabArchivesNotebookName", str)
LabArchivesRootPath = NewType("LabArchivesRootPath", str)
MimeType = NewType("MimeType", str)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]
StringMap: TypeAlias = Mapping[str, str]

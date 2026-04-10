from __future__ import annotations

from collections.abc import Mapping
from typing import NewType

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

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]
type StringMap = Mapping[str, str]

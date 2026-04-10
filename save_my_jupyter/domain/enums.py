from __future__ import annotations

from enum import StrEnum


class SnapshotSource(StrEnum):
    MANUAL = "manual"
    TRIGGER_CELL = "trigger_cell"
    WATCHED_PATH = "watched_path"


class CommitMode(StrEnum):
    PROMPT = "prompt"
    ALWAYS = "always"
    NEVER = "never"


class PathEventType(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


class ArtifactKind(StrEnum):
    NOTEBOOK = "notebook"
    FIGURE = "figure"
    FILE = "file"
    DIFF = "diff"


class TriggerMode(StrEnum):
    ALL_CELLS = "all_cells"
    MARKED_CELLS = "marked_cells"


class RepoHost(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    UNKNOWN = "unknown"

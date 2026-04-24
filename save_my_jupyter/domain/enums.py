from __future__ import annotations

from enum import StrEnum


class SnapshotSource(StrEnum):
    MANUAL = "manual"
    TRIGGER_CELL = "trigger_cell"


class CommitMode(StrEnum):
    PROMPT = "prompt"
    ALWAYS = "always"
    NEVER = "never"


class ArtifactKind(StrEnum):
    NOTEBOOK = "notebook"
    FIGURE = "figure"
    FILE = "file"
    DIFF = "diff"


class TriggerMode(StrEnum):
    ALL_CELLS = "all_cells"
    MARKED_CELLS = "marked_cells"

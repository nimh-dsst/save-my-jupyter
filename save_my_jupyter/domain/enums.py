from __future__ import annotations

from enum import Enum


class _ValueStrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class SnapshotSource(_ValueStrEnum):
    MANUAL = "manual"
    TRIGGER_CELL = "trigger_cell"


class CommitMode(_ValueStrEnum):
    # `ASK` is the rewrite's interactive mode (an in-panel prompt at snapshot
    # time); legacy `PROMPT` is retained as a back-compat alias for one release
    # (contracts C-GIT-02, C-CONFIG-07).
    ASK = "ask"
    PROMPT = "prompt"
    ALWAYS = "always"
    NEVER = "never"


class ArtifactKind(_ValueStrEnum):
    NOTEBOOK = "notebook"
    FIGURE = "figure"
    FILE = "file"
    DIFF = "diff"


class TriggerMode(_ValueStrEnum):
    ALL_CELLS = "all_cells"
    MARKED_CELLS = "marked_cells"

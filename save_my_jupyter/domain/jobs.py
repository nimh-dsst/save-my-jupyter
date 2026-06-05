from __future__ import annotations

from enum import Enum


class _ValueStrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class JobState(_ValueStrEnum):
    """Lifecycle of a snapshot job as the user observes it in the Activity feed.

    `abandoned` is set on Jupyter startup for any job left `queued` or `running`
    when the server stopped — a restart never leaves a job appearing to run
    forever (contract C-QUEUE-05).
    """

    QUEUED = "queued"
    RUNNING = "running"
    PERSISTED = "persisted"
    FAILED = "failed"
    ABANDONED = "abandoned"


class RunOutcome(_ValueStrEnum):
    """Outcome of the notebook execution that produced a snapshot, distinct from
    delivery `JobState`: an errored run can still be `persisted` with
    `run_outcome = error` (contracts C-SNAP-07, C-QUEUE-05)."""

    SUCCESS = "success"
    ERROR = "error"
    NOT_APPLICABLE = "n/a"

"""Pure job state-machine policy (target CONFIRM, contract C-QUEUE-05). The
durable Activity store enforces these rules; keeping them here makes the legal
lifecycle a single tested source of truth."""

from __future__ import annotations

from save_my_jupyter.domain.jobs import JobState

_ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.FAILED, JobState.ABANDONED}),
    JobState.RUNNING: frozenset(
        {JobState.PERSISTED, JobState.FAILED, JobState.ABANDONED}
    ),
    JobState.PERSISTED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.ABANDONED: frozenset(),
}
_TERMINAL_STATES = frozenset({JobState.PERSISTED, JobState.FAILED, JobState.ABANDONED})
_INFLIGHT_STATES = frozenset({JobState.QUEUED, JobState.RUNNING})


def can_transition(current: JobState, target: JobState) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def is_terminal(state: JobState) -> bool:
    return state in _TERMINAL_STATES


def abandon_if_pending(state: JobState) -> JobState:
    """Startup reconciliation: a job left in-flight when the server stopped is
    marked abandoned; terminal jobs are untouched (contract C-QUEUE-05)."""
    return JobState.ABANDONED if state in _INFLIGHT_STATES else state

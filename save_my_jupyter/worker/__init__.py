"""Background snapshot execution: a per-notebook FIFO worker pool so a notebook's
snapshots run in order while different notebooks proceed independently
(contract C-QUEUE-01). Uses stdlib threading only."""

from __future__ import annotations

from save_my_jupyter.worker.pool import WorkerPool

__all__ = ["WorkerPool"]

"""Per-notebook FIFO worker pool. Each notebook key gets its own queue and
worker thread, so jobs for one notebook run in submission order while different
notebooks run concurrently (contract C-QUEUE-01). Jobs must not raise; they own
their own error handling and record outcomes via the Activity store."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

_Job = Callable[[], None]


class WorkerPool:
    def __init__(self) -> None:
        self._queues: dict[str, queue.Queue[_Job | None]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._shutdown = False

    def submit(self, key: str, job: _Job) -> None:
        with self._lock:
            if self._shutdown:
                return
            work_queue = self._queues.get(key)
            if work_queue is None:
                work_queue = queue.Queue()
                self._queues[key] = work_queue
                thread = threading.Thread(
                    target=self._run, args=(work_queue,), daemon=True
                )
                self._threads[key] = thread
                thread.start()
        work_queue.put(job)

    def join(self) -> None:
        """Block until every queued job has finished (used by tests and a clean
        shutdown). Does not stop the worker threads."""
        for work_queue in self._snapshot_queues():
            work_queue.join()

    def shutdown(self, *, timeout: float | None = 5.0) -> None:
        with self._lock:
            self._shutdown = True
            queues = list(self._queues.items())
        for _key, work_queue in queues:
            work_queue.put(None)
        for key, _work_queue in queues:
            self._threads[key].join(timeout=timeout)

    def _snapshot_queues(self) -> list[queue.Queue[_Job | None]]:
        with self._lock:
            return list(self._queues.values())

    @staticmethod
    def _run(work_queue: queue.Queue[_Job | None]) -> None:
        while True:
            job = work_queue.get()
            if job is None:
                work_queue.task_done()
                return
            try:
                job()
            finally:
                work_queue.task_done()

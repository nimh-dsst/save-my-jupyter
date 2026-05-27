from __future__ import annotations

import threading

from save_my_jupyter.worker.pool import WorkerPool


def test_jobs_for_one_notebook_run_in_fifo_order() -> None:
    pool = WorkerPool()
    order: list[int] = []
    lock = threading.Lock()

    def make(index: int) -> None:
        with lock:
            order.append(index)

    try:
        for index in range(5):
            pool.submit("nb-a", lambda index=index: make(index))
        pool.join()
    finally:
        pool.shutdown()

    assert order == [0, 1, 2, 3, 4]


def test_different_notebooks_each_run_their_jobs() -> None:
    pool = WorkerPool()
    done: set[str] = set()
    lock = threading.Lock()

    def mark(label: str) -> None:
        with lock:
            done.add(label)

    try:
        pool.submit("nb-a", lambda: mark("a1"))
        pool.submit("nb-b", lambda: mark("b1"))
        pool.submit("nb-a", lambda: mark("a2"))
        pool.join()
    finally:
        pool.shutdown()

    assert done == {"a1", "b1", "a2"}


def test_submit_after_shutdown_is_ignored() -> None:
    pool = WorkerPool()
    pool.shutdown()
    ran: list[int] = []
    pool.submit("nb-a", lambda: ran.append(1))
    assert ran == []

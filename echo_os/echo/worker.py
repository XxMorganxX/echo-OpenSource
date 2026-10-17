"""Background threads: the single echo worker and the session sweeper.

One worker means one set of model calls at a time for the whole machine. Speech has its own
queue (`announcer.py`) so a long utterance never delays the next summary.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_STOP = object()


class QueueThread:
    """One daemon thread draining one queue, in order. Subclasses implement `_handle`."""

    def __init__(self, name: str):
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)

    def _put(self, item) -> None:
        self._queue.put(item)

    def _loop(self) -> None:
        while (item := self._queue.get()) is not _STOP:
            try:
                self._handle(item)
            except Exception:  # a bad item must never kill the thread
                logger.exception("%s failed on an item", self._thread.name)

    def _handle(self, item) -> None:
        raise NotImplementedError


class EchoWorker(QueueThread):
    def __init__(self, process: Callable, *, settle_seconds: float, sleep: Callable[[float], None] = time.sleep):
        super().__init__("echo-worker")
        self._process, self._settle_seconds, self._sleep = process, settle_seconds, sleep

    def submit(self, job) -> None:
        self._put(job)

    def _handle(self, job) -> None:
        # Give Claude Code a moment to flush the transcript's final lines.
        self._sleep(max(0.0, job.queued_at + self._settle_seconds - time.time()))
        self._process(job)


class PeriodicTask:
    def __init__(self, task: Callable[[], None], *, interval_seconds: float, name: str):
        self._task, self._interval = task, interval_seconds
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stopped.wait(self._interval):
            try:
                self._task()
            except Exception:
                logger.exception("%s failed", self._thread.name)

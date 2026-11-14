"""One background thread for all link I/O.

Serial and TCP calls can block for seconds; running them on the Tk thread
freezes the window. A single worker also serializes operations, so a
disconnect can never interleave with a call in progress. Results come back
through a queue that the Tk thread polls; no widget is touched off-thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("elevator_call_tester.ui")

Callback = Callable[[Any, BaseException | None], None]


class IoWorker:
    def __init__(self) -> None:
        self._tasks: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        self._busy = 0
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="io-worker", daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy > 0

    def submit(self, task: Callable[[], Any], callback: Callback | None = None) -> None:
        with self._lock:
            self._busy += 1
        self._tasks.put((task, callback))

    def _run(self) -> None:
        while True:
            item = self._tasks.get()
            if item is None:
                return
            task, callback = item
            try:
                result, error = task(), None
            except BaseException as ex:  # noqa: BLE001 - reported to the UI, never lost
                result, error = None, ex
            with self._lock:
                self._busy -= 1
            self._results.put((callback, result, error))

    def poll(self) -> int:
        """Run finished callbacks on the calling (Tk) thread. Returns how many ran."""
        ran = 0
        while True:
            try:
                callback, result, error = self._results.get_nowait()
            except queue.Empty:
                return ran
            if callback is not None:
                try:
                    callback(result, error)
                except Exception:  # a failing callback must not stop the polling loop
                    log.exception("UI callback failed")
            ran += 1

    def shutdown(self, timeout: float = 2.0) -> None:
        self._tasks.put(None)
        self._thread.join(timeout)

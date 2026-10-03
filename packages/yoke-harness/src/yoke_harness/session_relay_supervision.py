"""Bounded relay settlement without interpreter-exit joins on network workers."""

from concurrent.futures import Future
from contextlib import contextmanager
import logging
import queue
import threading
import time

from yoke_harness.session_relay_failure_log import FailureReporter


class SettlementPool:
    """Daemon workers: durable attempts, rather than Python threads, own jobs."""

    def __init__(self, max_workers: int):
        if max_workers < 1:
            raise ValueError("relay settlement requires at least one worker")
        self._queue = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        self._workers = [
            threading.Thread(target=self._work, daemon=True) for _ in range(max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, fn, *args):
        with self._lock:
            if self._closed:
                raise RuntimeError("relay settlement admission closed")
            future = Future()
            self._queue.put((future, fn, args))
            return future

    def _work(self):
        while True:
            task = self._queue.get()
            if task is None:
                return
            future, fn, args = task
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, *, wait=False, cancel_futures=False):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if cancel_futures:
                while True:
                    try:
                        task = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if task is not None:
                        task[0].cancel()
            for _ in self._workers:
                self._queue.put(None)
        if wait:
            for worker in self._workers:
                worker.join()


class RelayStopRequested(BaseException):
    """Unwind blocking main-thread IO without treating logout as a poll failure."""


class Supervisor:
    def __init__(self, max_workers: int, failures: FailureReporter, stop):
        self.pool = SettlementPool(max_workers)
        self.failures = failures
        self.stop = stop
        self.pending = []
        self.lock = threading.Lock()
        self.settled = 0

    def dispatch(self, settle):
        if self.stop.is_set():
            return
        future = self.pool.submit(self._guarded, settle)
        with self.lock:
            self.pending = [f for f in self.pending if not f.done()]
            self.pending.append(future)

    def _guarded(self, settle):
        if self.stop.reason.startswith("signal:"):
            return None
        try:
            try:
                outcome = settle()
            except Exception as exc:  # noqa: BLE001 — isolate a leased job
                self.failures.failed("job settlement", f"{type(exc).__name__}: {exc}")
                return None
            state = str(getattr(outcome, "state", ""))
            if state == "report_failed":
                self.failures.failed(
                    "report", getattr(outcome, "error_code", None) or state
                )
            else:
                self.failures.recovered("job settlement")
                if state == "reported":
                    self.failures.recovered("report")
            return outcome
        finally:
            with self.lock:
                self.settled += 1

    def drain(self, *, timeout):
        deadline = time.monotonic() + max(0, timeout)
        while True:
            with self.lock:
                self.pending = [f for f in self.pending if not f.done()]
                outstanding = bool(self.pending)
            remaining = deadline - time.monotonic()
            if not outstanding or remaining <= 0:
                return
            time.sleep(min(0.05, remaining))


@contextmanager
def refreshing_inventory(refresher):
    """Join a normal refresh; interruption leaves a daemon worker, never an exit join."""
    pool = SettlementPool(1) if refresher else None
    refresh = pool.submit(refresher) if pool else None
    try:
        yield
        if refresh:
            try:
                refresh.result()
            except Exception:
                logging.getLogger(__name__).warning(
                    "relay surface probe refresh failed", exc_info=True
                )
    finally:
        if pool:
            pool.shutdown(wait=False, cancel_futures=True)

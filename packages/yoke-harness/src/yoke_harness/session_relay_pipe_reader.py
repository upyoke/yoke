"""Bounded timed pipe reads on Windows and Unix, with one durable reader."""

import os
import queue
import threading


class PipeReader:
    """Keep queued bytes when a startup probe hands stdout to its turn owner."""

    def __init__(self, stream):
        self.stream = stream
        self.chunks = queue.Queue(maxsize=8)
        self.stopped = threading.Event()
        self.eof = False
        self.thread = threading.Thread(target=self._drain, daemon=True, name="relay-pipe-reader")
        self.thread.start()

    def _drain(self):
        try:
            while not self.stopped.is_set():
                chunk = os.read(self.stream.fileno(), 65536)
                self._put(chunk)
                if not chunk:
                    return
        except (OSError, ValueError) as exc:
            self._put(exc)

    def _put(self, value):
        while not self.stopped.is_set():
            try:
                self.chunks.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def read(self, size=65536, *, timeout=None):
        if self.eof:
            return b""
        try:
            value = self.chunks.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("relay pipe read deadline expired") from None
        if isinstance(value, Exception):
            self.eof = True
            raise value
        self.eof = not value
        return value

    def close(self):
        self.stopped.set()

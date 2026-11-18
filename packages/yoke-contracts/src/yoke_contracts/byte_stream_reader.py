"""Bounded, timed byte reads from subprocess pipes on every host platform."""

from __future__ import annotations

import os
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import BinaryIO


class ByteStreamReader:
    """Read both pipes without waiting for newlines or selecting Windows handles.

    Each event is ``(stream, bytes)``; empty bytes mark that stream's EOF.
    ``read`` returns None only when its timeout expires. The caller owns the
    streams and must stop its child before leaving early, then may drain EOF.
    Reader errors propagate to the consuming thread. A bounded queue keeps a
    slow consumer from retaining the child's entire output.
    """

    def __init__(self, streams: tuple[BinaryIO, ...], *, chunk_size: int = 8192):
        if chunk_size <= 0:
            raise ValueError("pipe reader chunk_size must be positive")
        self._remaining = set(streams)
        self._events: Queue[tuple[BinaryIO, bytes | Exception]] = Queue(maxsize=16)
        self._stop = Event()
        self._threads = [
            Thread(target=self._pump, args=(stream, chunk_size), daemon=True)
            for stream in self._remaining
        ]

    @property
    def pending(self) -> bool:
        return bool(self._remaining)

    def _publish(self, stream: BinaryIO, value: bytes | Exception) -> None:
        while not self._stop.is_set():
            try:
                self._events.put((stream, value), timeout=0.1)
                return
            except Full:
                pass

    def _pump(self, stream: BinaryIO, chunk_size: int) -> None:
        try:
            while not self._stop.is_set():
                chunk = os.read(stream.fileno(), chunk_size)
                self._publish(stream, chunk)
                if not chunk:
                    return
        except Exception as exc:
            self._publish(stream, exc)

    def read(self, timeout: float | None = None) -> tuple[BinaryIO, bytes] | None:
        if not self.pending:
            return None
        try:
            stream, value = self._events.get(timeout=timeout)
        except Empty:
            return None
        if isinstance(value, Exception):
            self._remaining.discard(stream)
            raise value
        if not value:
            self._remaining.remove(stream)
        return stream, value

    def __enter__(self) -> ByteStreamReader:
        for thread in self._threads:
            thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1)

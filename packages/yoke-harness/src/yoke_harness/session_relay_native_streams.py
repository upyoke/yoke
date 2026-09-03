"""Read a native's two streams without ever growing with what it says.

A native can talk for an hour, so nothing that holds its output may hold all
of it. One bounded pair, drained on its own threads, is what every capture
path shares: the supervisor watching a detached turn, and the transports that
own a native's pipes for the length of a poll.
"""

from __future__ import annotations

import threading
from typing import IO

from yoke_harness.session_relay_native_capture_format import STREAM_BUDGET_BYTES


STDOUT = "stdout"
STDERR = "stderr"
_READ_CHUNK_BYTES = 8 * 1024


class BoundedStreams:
    """One native's two capped streams, and whether they have changed."""

    def __init__(self, budget: int = STREAM_BUDGET_BYTES) -> None:
        self.budget = budget
        self._streams = {STDOUT: bytearray(), STDERR: bytearray()}
        self._lock = threading.Lock()
        self._dirty = True

    def append(self, name: str, chunk: bytes) -> None:
        with self._lock:
            buffer = self._streams[name]
            room = self.budget - len(buffer)
            if room > 0:
                buffer.extend(chunk[:room])
                self._dirty = True

    def take_dirty(self) -> bool:
        """Report whether anything arrived since the last time this was asked."""
        with self._lock:
            was_dirty, self._dirty = self._dirty, False
            return was_dirty

    def snapshot(self) -> tuple[bytes, bytes]:
        with self._lock:
            return bytes(self._streams[STDOUT]), bytes(self._streams[STDERR])


def drain(stream: IO[bytes] | None, streams: BoundedStreams, name: str) -> None:
    """Read one pipe to its end, keeping only what the bound allows."""
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                return
            streams.append(name, chunk)
    except (OSError, ValueError):
        return


def start_drain(
    stream: IO[bytes] | None,
    streams: BoundedStreams,
    name: str,
    *,
    daemon: bool = True,
) -> threading.Thread | None:
    """Drain one pipe on its own thread, or return ``None`` when there is none."""
    if stream is None:
        return None
    thread = threading.Thread(
        target=drain,
        args=(stream, streams, name),
        daemon=daemon,
        name=f"yoke-native-{name}",
    )
    thread.start()
    return thread


__all__ = [
    "STDERR",
    "STDOUT",
    "BoundedStreams",
    "drain",
    "start_drain",
]

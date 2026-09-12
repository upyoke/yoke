"""Read a native's two streams without ever growing with what it says.

A native can talk for an hour, so nothing that holds its output may hold all
of it. One bounded pair, drained on its own threads, is what every capture
path shares: the supervisor watching a detached turn, and the transports that
own a native's pipes for the length of a poll.

What a bound drops matters as much as that it drops something. Keeping
only the beginning loses precisely the two things a capture is read for:
the line a native failed on, and the result object a print-mode turn
prints as it exits — which is where a Cursor turn states the tokens it
consumed. So each stream keeps its head, keeps as much of its tail as the
same budget allows, and says how many bytes it dropped between them.
"""

from __future__ import annotations

import threading
from typing import IO

from yoke_harness.session_relay_native_capture_format import (
    ELISION_NOTICE_BYTES,
    STREAM_BUDGET_BYTES,
    elision_notice,
)


STDOUT = "stdout"
STDERR = "stderr"
_READ_CHUNK_BYTES = 8 * 1024

#: Share of a stream's budget held for its opening lines — a native's
#: startup, its banner, the identity it announces once.
_HEAD_SHARE = 4

#: Below this, a budget cannot hold a head, a tail, and a notice saying
#: what fell between them, so it simply keeps the beginning.
_MIN_SPLIT_BUDGET = 4 * ELISION_NOTICE_BYTES


class BoundedStreams:
    """One native's two capped streams, and whether they have changed."""

    def __init__(self, budget: int = STREAM_BUDGET_BYTES) -> None:
        self.budget = budget
        split = budget >= _MIN_SPLIT_BUDGET
        self._head_budget = budget // _HEAD_SHARE if split else budget
        self._tail_budget = (
            budget - self._head_budget - ELISION_NOTICE_BYTES if split else 0
        )
        self._heads = {STDOUT: bytearray(), STDERR: bytearray()}
        self._tails = {STDOUT: bytearray(), STDERR: bytearray()}
        self._elided = {STDOUT: 0, STDERR: 0}
        self._lock = threading.Lock()
        self._dirty = True

    def append(self, name: str, chunk: bytes) -> None:
        with self._lock:
            head = self._heads[name]
            room = self._head_budget - len(head)
            if room > 0:
                head.extend(chunk[:room])
                chunk = chunk[room:]
                self._dirty = True
            if not chunk or self._tail_budget <= 0:
                return
            tail = self._tails[name]
            tail.extend(chunk)
            self._dirty = True
            excess = len(tail) - self._tail_budget
            if excess > 0:
                del tail[:excess]
                self._elided[name] += excess

    def take_dirty(self) -> bool:
        """Report whether anything arrived since the last time this was asked."""
        with self._lock:
            was_dirty, self._dirty = self._dirty, False
            return was_dirty

    def snapshot(self) -> tuple[bytes, bytes]:
        with self._lock:
            return self._retained(STDOUT), self._retained(STDERR)

    def _retained(self, name: str) -> bytes:
        """Render one stream: its head, what it dropped, and its tail."""
        head = bytes(self._heads[name])
        tail = bytes(self._tails[name])
        elided = self._elided[name]
        if not elided:
            return head + tail
        return b"".join((head, b"\n", elision_notice(elided), b"\n", tail))


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

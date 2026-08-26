"""Keep a bounded tail of an ACP child's stderr for failure diagnosis.

The ACP child used to be started with ``stderr`` pointed at ``/dev/null``,
which is fine right up until the exchange fails: the transport then reports
that something went wrong and carries nothing that says what, and the launch
row inherits that emptiness all the way to its deadline.

Draining is not optional even when nobody reads the result. A child whose
stderr pipe fills stops writing and then stops working, so the tail is read
continuously on its own thread and only the last :data:`STDERR_TAIL_BYTES`
are kept — enough for a traceback or a refusal line, bounded enough to hold
in memory for every concurrent launch on a machine.
"""

from __future__ import annotations

import threading
from typing import IO


# One half of the per-diagnostic stream budget the retention layer allows.
STDERR_TAIL_BYTES = 64 * 1024


class BoundedStderr:
    """Continuously drain one child stream, keeping only its recent tail."""

    def __init__(
        self, stream: IO[bytes] | None, *, limit: int = STDERR_TAIL_BYTES
    ) -> None:
        self._limit = max(0, int(limit))
        self._lock = threading.Lock()
        self._tail = bytearray()
        self._stream = stream
        if stream is None:
            return
        self._thread = threading.Thread(
            target=self._drain,
            daemon=True,
            name="yoke-cursor-acp-stderr",
        )
        self._thread.start()

    def _drain(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with self._lock:
                    self._tail.extend(chunk)
                    if len(self._tail) > self._limit:
                        del self._tail[: len(self._tail) - self._limit]
        except (OSError, ValueError):
            return

    def tail(self) -> bytes:
        """Return the bytes kept so far; safe to call while the child runs."""
        with self._lock:
            return bytes(self._tail)


def native_diagnostic_fields(client: object) -> dict[str, object]:
    """Return what an ACP child said and how it exited, if anything."""
    drain = getattr(client, "stderr", None)
    process = getattr(client, "process", None)
    if not isinstance(drain, BoundedStderr) or process is None:
        return {}
    fields: dict[str, object] = {}
    tail = drain.tail()
    if tail:
        fields["native_stderr"] = tail
    exit_code = process.poll()
    if exit_code is not None:
        fields["exit_code"] = int(exit_code)
    return fields


__all__ = ["STDERR_TAIL_BYTES", "BoundedStderr", "native_diagnostic_fields"]

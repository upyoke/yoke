"""Stderr progress so snapshot sync is visibly working, not wedged."""

from __future__ import annotations

import sys
import time
from typing import Optional, TextIO

DEFAULT_MIN_INTERVAL_S = 2.0


class ScanProgress:
    """Throttle snapshot-scan status lines to stderr.

    Watchers and tool timeouts treat silence as a hang. The first and last
    lines always flush; intermediate lines emit at least every
    ``min_interval_s`` seconds.
    """

    def __init__(
        self,
        stream: Optional[TextIO] = None,
        *,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    ) -> None:
        self._stream = sys.stderr if stream is None else stream
        self._min_interval_s = min_interval_s
        self._started = time.monotonic()
        self._last_emit = 0.0

    def emit(self, message: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_emit) < self._min_interval_s:
            return
        elapsed = int(now - self._started)
        self._stream.write(f"snapshot sync: {message} ({elapsed}s elapsed)\n")
        self._stream.flush()
        self._last_emit = now

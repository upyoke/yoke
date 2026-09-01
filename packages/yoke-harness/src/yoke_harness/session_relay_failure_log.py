"""One useful stderr line per failure burst, and one when it recovers.

A relay operation that fails every cycle would otherwise either flood the
log or say nothing at all. Both outcomes hide the same fact: which
operation is failing, with what reason, and for how long.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Callable


FAILURE_LOG_INTERVAL_SECONDS = 300

_LOGGER = logging.getLogger(__name__)


@dataclass
class _FailureBurst:
    count: int
    started_at: float
    last_logged_at: float


@dataclass
class FailureReporter:
    """Write one useful line per failure burst and one when it recovers."""

    interval_seconds: float = FAILURE_LOG_INTERVAL_SECONDS
    clock: Callable[[], float] = time.monotonic
    bursts: dict[str, _FailureBurst] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def failed(self, operation: str, reason: object) -> None:
        now = self.clock()
        detail = " ".join(str(reason).splitlines()).strip() or "unknown failure"
        with self.lock:
            burst = self.bursts.get(operation)
            if burst is None:
                burst = _FailureBurst(1, now, now)
                self.bursts[operation] = burst
            else:
                burst.count += 1
                if now - burst.last_logged_at < self.interval_seconds:
                    return
                burst.last_logged_at = now
            _LOGGER.error(
                "relay %s failed: %s; consecutive_failures=%d elapsed_seconds=%.1f",
                operation,
                detail,
                burst.count,
                max(0.0, now - burst.started_at),
            )

    def recovered(self, operation: str) -> None:
        now = self.clock()
        with self.lock:
            burst = self.bursts.pop(operation, None)
        if burst is not None:
            _LOGGER.warning(
                "relay %s recovered; consecutive_failures=%d elapsed_seconds=%.1f",
                operation,
                burst.count,
                max(0.0, now - burst.started_at),
            )


__all__ = ["FAILURE_LOG_INTERVAL_SECONDS", "FailureReporter"]

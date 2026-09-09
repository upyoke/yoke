"""One useful stderr line per failure burst, and one when it recovers.

A relay operation that fails every cycle would otherwise either flood the
log or say nothing at all. Both outcomes hide the same fact: which
operation is failing, with what reason, and for how long.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Callable

from yoke_cli.transport.https_retry_policy import utc_stamp


FAILURE_LOG_INTERVAL_SECONDS = 300

_LOGGER = logging.getLogger(__name__)


def _wall_now() -> datetime:
    return datetime.now(timezone.utc)


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
    stamp_clock: Callable[[], datetime] = _wall_now
    bursts: dict[str, _FailureBurst] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    state_dir: Path | None = None

    def failed(
        self, operation: str, reason: object, *, persist_code: str | None = None
    ) -> None:
        now = self.clock()
        detail = " ".join(str(reason).splitlines()).strip() or "unknown failure"
        if operation == "poll" and self.state_dir is not None:
            from yoke_harness.session_relay_poll_health import (
                diagnosed_poll_code,
                record_poll_failure,
            )

            record_poll_failure(
                self.state_dir,
                error_code=diagnosed_poll_code(
                    persist_code if persist_code is not None else reason
                ),
            )
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
                "%s relay %s failed: %s; class=relay_failure "
                "consecutive_failures=%d elapsed_seconds=%.1f outcome=retrying",
                utc_stamp(self.stamp_clock),
                operation,
                detail,
                burst.count,
                max(0.0, now - burst.started_at),
            )

    def recovered(self, operation: str) -> None:
        now = self.clock()
        if operation == "poll" and self.state_dir is not None:
            from yoke_harness.session_relay_poll_health import record_poll_success

            record_poll_success(self.state_dir)
        with self.lock:
            burst = self.bursts.pop(operation, None)
        if burst is not None:
            _LOGGER.warning(
                "%s relay %s recovered; class=relay_recovery "
                "consecutive_failures=%d elapsed_seconds=%.1f outcome=recovered",
                utc_stamp(self.stamp_clock),
                operation,
                burst.count,
                max(0.0, now - burst.started_at),
            )


__all__ = ["FAILURE_LOG_INTERVAL_SECONDS", "FailureReporter"]

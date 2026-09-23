"""Bounded in-process waiting for a deployment QA stage."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


AWAITING_SCOPED_QA = -4
DEFAULT_POLL_INTERVAL_SECONDS = 15.0


def dispatch_until_qa_resolves(
    dispatch: Callable[..., tuple[int, str]],
    *args: Any,
    timeout_seconds: float,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> tuple[int, str]:
    """Re-dispatch while scoped QA is pending, bounded by ``timeout_seconds``.

    The first dispatch is immediate. A zero timeout preserves a deliberate
    single-probe caller, while the ordinary pipeline's thirty-minute timeout
    keeps its process alive until the QA stage can advance on its own.
    """
    result = dispatch(*args, **kwargs)
    if result[0] != AWAITING_SCOPED_QA:
        return result

    timeout = max(0.0, float(timeout_seconds))
    deadline = monotonic() + timeout
    interval = max(0.001, float(poll_interval_seconds))
    while monotonic() < deadline:
        sleep(min(interval, max(0.0, deadline - monotonic())))
        result = dispatch(*args, **kwargs)
        if result[0] != AWAITING_SCOPED_QA:
            return result

    detail = str(result[1] or "scoped QA remains unresolved")
    return AWAITING_SCOPED_QA, (
        f"{detail}; timed out after {timeout:g}s awaiting scoped QA. "
        "Settle or waive the outstanding member obligations, then re-drive "
        "this deployment run from the QA stage."
    )


__all__ = [
    "AWAITING_SCOPED_QA",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "dispatch_until_qa_resolves",
]

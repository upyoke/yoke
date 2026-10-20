"""Bounded in-process waiting for a deployment QA stage.

Two answers mean "ask again on the next check" rather than an outcome: scoped
QA still pending (``-4``), and a dispatch the control plane refused because
another transaction held the run (``-6``, from a ``run_busy``, lock-timeout
or cancelled-statement answer). Neither may fail the run; both re-dispatch on
the same cadence until the stage answers or the wait times out resumably.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from yoke_contracts.designed_wait import announce_designed_wait, poll_every

AWAITING_SCOPED_QA = -4
RETRY_NEXT_CHECK = -6
_REDISPATCH = frozenset({AWAITING_SCOPED_QA, RETRY_NEXT_CHECK})
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
    if result[0] not in _REDISPATCH:
        return result

    timeout = max(0.0, float(timeout_seconds))
    deadline = monotonic() + timeout
    interval = max(0.001, float(poll_interval_seconds))
    if timeout > 0:
        announce_designed_wait(
            "scoped QA obligations on this deployment run to settle",
            max_wait_seconds=timeout,
            cadence=poll_every(interval),
            write=print,
        )
    while monotonic() < deadline:
        if result[0] == RETRY_NEXT_CHECK:
            print(f"Dispatch refused while the run was busy; retrying in {interval:g}s. {result[1]}")
        sleep(min(interval, max(0.0, deadline - monotonic())))
        result = dispatch(*args, **kwargs)
        if result[0] not in _REDISPATCH:
            return result

    if result[0] == RETRY_NEXT_CHECK:
        # Resumable like pending QA: the run stays in this stage, unfailed.
        return AWAITING_SCOPED_QA, (
            f"{result[1]}; the run stayed busy for {timeout:g}s of re-dispatch. "
            "The run was left in this stage and was not failed; re-drive it "
            "from this stage once the named holder finishes."
        )
    detail = str(result[1] or "scoped QA remains unresolved")
    return AWAITING_SCOPED_QA, (
        f"{detail}; timed out after {timeout:g}s awaiting scoped QA. "
        "Settle or waive the outstanding member obligations, then re-drive "
        "this deployment run from the QA stage."
    )


__all__ = [
    "AWAITING_SCOPED_QA",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "RETRY_NEXT_CHECK",
    "dispatch_until_qa_resolves",
]

"""Bounded in-process waiting for a deployment QA stage."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextvars import copy_context
from typing import Any

from yoke_contracts.designed_wait import (
    announce_designed_wait,
    format_duration,
    poll_every,
)

AWAITING_SCOPED_QA = -4
DEFAULT_POLL_INTERVAL_SECONDS = 15.0
#: Polls between status lines, so a silent capture means stuck, not busy.
STATUS_EVERY_POLLS = 4


def _print_now(line: str) -> None:
    print(line, flush=True)


def _dispatch_within(
    seconds: float,
    dispatch: Callable[..., tuple[int, str]],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[int, str] | None:
    """One dispatch, or ``None`` when it has no answer within *seconds*.

    A dispatch blocked on a lock wait or a hung socket cannot be interrupted
    from Python, so the wait stops waiting for it. The worker is a daemon
    thread the driver never joins: the stage dispatch is idempotent, so the
    re-drive the timeout names repeats whatever the abandoned call left.
    """
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["result"] = dispatch(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller
            outcome["error"] = exc

    worker = threading.Thread(
        target=copy_context().run,
        args=(run,),
        name="deployment-qa-dispatch",
        daemon=True,
    )
    worker.start()
    worker.join(max(0.0, seconds))
    if worker.is_alive():
        return None
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def _blocker_count(detail: str) -> int:
    """The dispatch joins one reason per waiting subject with ``"; "``."""
    return len([part for part in str(detail or "").split("; ") if part.strip()])


def dispatch_until_qa_resolves(
    dispatch: Callable[..., tuple[int, str]],
    *args: Any,
    timeout_seconds: float,
    fingerprint: Callable[[], str],
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    write: Callable[[str], None] = _print_now,
    **kwargs: Any,
) -> tuple[int, str]:
    """Dispatch on changed QA facts and at the deadline while scoped QA is pending.

    The first dispatch is immediate and unbounded: it runs whatever stage
    the driver is on. Once that stage answers scoped-QA pending, each
    re-dispatch gets only the time left on the wait's deadline, so a blocked
    call ends the wait with its timeout and recovery rather than silence.
    A zero timeout preserves a deliberate single-probe caller.
    """
    observed = fingerprint()
    result = dispatch(*args, **kwargs)
    if result[0] != AWAITING_SCOPED_QA:
        return result

    timeout = max(0.0, float(timeout_seconds))
    started = monotonic()
    deadline = started + timeout
    interval = max(0.001, float(poll_interval_seconds))
    if timeout > 0:
        announce_designed_wait(
            "scoped QA obligations on this deployment run to settle",
            max_wait_seconds=timeout,
            cadence=(
                f"{poll_every(interval)}; prints a status line every "
                f"{format_duration(interval * STATUS_EVERY_POLLS)}"
            ),
            silent=False,
            write=write,
        )
    polls = 0
    unanswered = ""
    while monotonic() < deadline:
        sleep(min(interval, max(0.0, deadline - monotonic())))

        def poll():
            nonlocal observed
            current = fingerprint()
            if current != observed:
                observed = current
                return dispatch(*args, **kwargs)
            return result

        # At the deadline attempt dispatch directly, without another read.
        check = (lambda: dispatch(*args, **kwargs)) if monotonic() >= deadline else poll
        answer = _dispatch_within(deadline - monotonic(), check, (), {})
        if answer is None:
            unanswered = "; the last QA dispatch or fingerprint read had no answer when the deadline passed"
            break
        result = answer
        if result[0] != AWAITING_SCOPED_QA:
            return result
        polls += 1
        if polls % STATUS_EVERY_POLLS == 0:
            write(
                "Still waiting for scoped QA: "
                f"{format_duration(monotonic() - started)} elapsed of "
                f"{format_duration(timeout)}; {_blocker_count(result[1])} "
                "blocker(s) outstanding."
            )

    detail = str(result[1] or "scoped QA remains unresolved")
    return AWAITING_SCOPED_QA, (
        f"{detail}; timed out after {timeout:g}s awaiting scoped QA"
        f"{unanswered}. Settle or waive the outstanding member obligations, "
        "then re-drive this deployment run from the QA stage."
    )


__all__ = [
    "AWAITING_SCOPED_QA",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "STATUS_EVERY_POLLS",
    "dispatch_until_qa_resolves",
]

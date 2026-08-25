"""Which relay failures are worth another attempt, and how long to wait.

Two failure shapes reach the relay client and they do not deserve the same
budget.

A *connection-level* failure — a reset, a name that did not resolve, a
gateway answering for a box that is restarting — means the envelope
probably never reached a handler. Waiting a moment and asking again is
almost always right, so these get the full attempt budget with backoff
between tries.

A *response-deadline* failure means the server accepted the envelope and is
still working on it. Asking again re-runs whatever it is doing, so these
keep the single immediate re-attempt they have always had and no backoff:
the point of that one retry is the idempotency ledger, which replays an
already-completed call instead of running it twice.

Retrying at all is only safe because the envelope is serialized once, so
every attempt carries the same ``request_id``, and the dispatcher ledgers
only successful side-effecting calls. A completed call replays; a failed or
never-run one proceeds fresh.
"""

from __future__ import annotations

import sys
from typing import TextIO


CONNECTION_ATTEMPTS = 7
CONNECTION_BACKOFF_SECONDS = (1.0, 3.0, 6.0, 12.0, 24.0, 48.0)
RESPONSE_DEADLINE_ATTEMPTS = 2


def http_status_is_transient(status: int | None) -> bool:
    """Whether an HTTP status describes the relay, not the request.

    5xx is the box: a gateway with nothing behind it yet, a process still
    coming up, a proxy that gave up on an upstream. Everything else is an
    answer about this request — an authentication rejection, an
    authorization refusal, a malformed payload — and asking again produces
    the same answer.
    """
    try:
        code = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return code >= 500


def connection_backoff_seconds(attempt: int) -> float:
    """Seconds to wait before the attempt following a zero-based attempt."""
    backoff = CONNECTION_BACKOFF_SECONDS
    if not backoff:
        return 0.0
    return backoff[min(max(attempt, 0), len(backoff) - 1)]


def write_retry_notice(
    reason: str,
    attempt: int,
    backoff_seconds: float,
    stream: TextIO | None = None,
) -> None:
    """Say that the relay is waiting, so a long retry is never silent.

    The full attempt budget spends 94 seconds of backoff on top of seven
    request timeouts, which is minutes of wall clock. Without a line per
    attempt the operator cannot tell a relay that is patiently retrying
    from a command that has hung, and the observed report is exactly that:
    zero output, no receipt, and no way to know which one happened.
    """
    print(
        f"note: relay attempt {attempt + 1}/{CONNECTION_ATTEMPTS} failed "
        f"({reason}); retrying in {backoff_seconds:.0f}s",
        file=sys.stderr if stream is None else stream,
        flush=True,
    )


__all__ = [
    "CONNECTION_ATTEMPTS",
    "CONNECTION_BACKOFF_SECONDS",
    "RESPONSE_DEADLINE_ATTEMPTS",
    "connection_backoff_seconds",
    "write_retry_notice",
    "http_status_is_transient",
]

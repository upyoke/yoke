"""Which relay failures are worth another attempt, and how long to wait.

Two failure shapes reach the relay client and they do not deserve the same
budget.

A *connection-level* failure — a reset, a name that did not resolve, a
gateway answering for a box that is restarting — means the envelope
probably never reached a handler. Waiting a moment and asking again is
almost always right, so these get the full attempt budget with backoff
between tries.

Not every connection-level failure deserves that budget, though. A
refused connection to a loopback address is already the final answer:
nothing is listening on this machine's port, and no amount of waiting
starts a server the operator has not started. Spending 95 seconds of
backoff there reports minutes late what was known immediately.

A *response-deadline* failure means the server accepted the envelope and is
still working on it. These keep one immediate re-attempt and no backoff. The
dispatcher serializes a repeated side-effecting ``request_id`` behind the
in-flight call, then the idempotency ledger replays its completed result.

Retrying at all is only safe because the envelope is serialized once, so every
attempt carries the same ``request_id``. The dispatcher serializes concurrent
copies and ledgers only successful side-effecting calls: a completed call
replays, while a failed or never-run call proceeds fresh.
"""

from __future__ import annotations

import errno
import ipaddress
import sys
import urllib.error
from typing import TextIO
from urllib.parse import urlsplit


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


def should_retry_connection(
    attempt: int,
    api_url: str = "",
    error: BaseException | None = None,
    budget: int = CONNECTION_ATTEMPTS,
) -> bool:
    """Whether a connection-level failure is worth another attempt.

    Two independent reasons to stop: the attempt budget is spent, or the
    failure already carries its own final answer. A caller whose own answer
    to a refusal is "report it and carry on" passes a smaller ``budget``:
    the full ladder is the right patience for a call the caller cannot
    proceed without, and far too much for one it can.
    """
    if attempt + 1 >= budget:
        return False
    return not connection_refusal_is_conclusive(api_url, error)


def connection_refusal_is_conclusive(
    api_url: str,
    error: BaseException | None,
) -> bool:
    """Whether a failed connection has already answered for good.

    A hostname can front a fleet where one box is restarting, so a refusal
    there is worth asking again. A loopback endpoint is this machine: the
    kernel refused because no process holds that port, and it will keep
    refusing until the operator starts one. A sandbox denial answers for
    good wherever it happens — the policy that blocked the connect blocks
    every retry too, so spending the budget only makes the wait longer
    before the same verdict.
    """
    if is_sandbox_denial(error):
        return True
    return _is_connection_refused(error) and _host_is_loopback(api_url)


def is_sandbox_denial(error: BaseException | None) -> bool:
    """Whether the OS refused the connect on policy rather than on reachability."""
    return _unwrapped_errno(error) in (errno.EPERM, errno.EACCES)


def _unwrapped_errno(error: BaseException | None) -> int | None:
    candidate = error
    if isinstance(candidate, urllib.error.URLError):
        reason = candidate.reason
        candidate = reason if isinstance(reason, BaseException) else candidate
    return getattr(candidate, "errno", None)


def _is_connection_refused(error: BaseException | None) -> bool:
    candidate = error
    if isinstance(candidate, urllib.error.URLError):
        reason = candidate.reason
        candidate = reason if isinstance(reason, BaseException) else candidate
    if isinstance(candidate, ConnectionRefusedError):
        return True
    return _unwrapped_errno(error) == errno.ECONNREFUSED


def _host_is_loopback(api_url: str) -> bool:
    try:
        host = urlsplit(str(api_url or "")).hostname or ""
    except ValueError:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


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
    "connection_refusal_is_conclusive",
    "is_sandbox_denial",
    "should_retry_connection",
    "CONNECTION_BACKOFF_SECONDS",
    "RESPONSE_DEADLINE_ATTEMPTS",
    "connection_backoff_seconds",
    "write_retry_notice",
    "http_status_is_transient",
]

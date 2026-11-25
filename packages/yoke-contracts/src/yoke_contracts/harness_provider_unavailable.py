"""A harness probe whose provider never answered: shared by runner and server.

A real-request probe that started and then timed out with no reply and no
error event reads as provider-unavailable rather than a broken host. The
harness runner retries one such stall per run; the owed-reset caller turns a
retry off when the host's last reset already ended this way, and the server
records the code so the debt stays owed and the next execution retries it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

PROVIDER_UNAVAILABLE_ERROR_CODE = "harness_provider_unavailable"
PROVIDER_UNAVAILABLE_RECOVERY = (
    "provider unavailable; the owed reset retries with the next execution"
)

_stall_retry = ContextVar("baseline_probe_stall_retry", default=True)


def stall_retry_allowed() -> bool:
    """Whether probes run in this scope may retry one provider stall."""
    return _stall_retry.get()


@contextmanager
def probe_stall_retry(allowed: bool) -> Iterator[None]:
    """Scope the probes a baseline reach runs to retry, or not, one stall."""
    token = _stall_retry.set(allowed)
    try:
        yield
    finally:
        _stall_retry.reset(token)


__all__ = [
    "PROVIDER_UNAVAILABLE_ERROR_CODE",
    "PROVIDER_UNAVAILABLE_RECOVERY",
    "probe_stall_retry",
    "stall_retry_allowed",
]

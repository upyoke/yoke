"""Retry merge-preflight reads that lose the machine GitHub operation lock."""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_READ_ATTEMPTS,
    retry_backoff_seconds,
)

T = TypeVar("T")

MACHINE_OPERATION_BUSY_CODE = "github_machine_operation_busy"
_BUSY_MESSAGE_TOKEN = "holding the machine operation lock"


def is_machine_operation_busy_response(response: Any) -> bool:
    """True only for the self-classified transient machine-lock refusal."""

    error = getattr(response, "error", None)
    if error is None:
        return False
    if str(getattr(error, "code", "") or "") == MACHINE_OPERATION_BUSY_CODE:
        return True
    return _BUSY_MESSAGE_TOKEN in str(getattr(error, "message", "") or "")


def call_with_machine_lock_retry(
    call: Callable[[], T],
    *,
    sleep: Callable[[float], Any] = time.sleep,
    attempts: int = GITHUB_AUTH_READ_ATTEMPTS,
) -> T:
    """Replay *call* while it reports machine-lock contention.

    Non-transient failures return immediately. The attempt bound and
    backoff come from the shared GitHub-auth transience constants.
    """

    last: T | None = None
    for attempt in range(attempts):
        last = call()
        if not is_machine_operation_busy_response(last):
            return last
        if attempt + 1 >= attempts:
            return last
        sleep(retry_backoff_seconds(attempt))
    assert last is not None
    return last


__all__ = [
    "MACHINE_OPERATION_BUSY_CODE",
    "call_with_machine_lock_retry",
    "is_machine_operation_busy_response",
]

"""Bounded same-intent retry for typed GitHub workflow dispatch."""

from __future__ import annotations

import time
from typing import Any, Callable, Sequence


TRIGGER_RECOVERY_RETRY_LIMIT = 6
TRIGGER_RECOVERY_INTERVAL_SECONDS = 5
_RECOVERABLE_CODES = (
    "workflow_dispatch_ambiguous",
    "workflow_dispatch_pending",
    "workflow_dispatch_state_unavailable",
    "rest_transport_error",
)


def _recoverable(result: Any) -> bool:
    if result.returncode != 4:
        return False
    detail = f"{result.stderr or ''}\n{result.stdout or ''}"
    return any(code in detail for code in _RECOVERABLE_CODES)


def trigger_with_recovery_retries(
    args: Sequence[str],
    *,
    github_actions: Callable[..., Any],
    project: str,
    sd: str | None,
    timeout_sec: int,
) -> Any:
    """Retry only recoverable operation errors with identical dispatch args."""
    deadline = time.monotonic() + max(0, timeout_sec)
    result = github_actions(*args, project=project, sd=sd)
    for attempt in range(1, TRIGGER_RECOVERY_RETRY_LIMIT):
        if not _recoverable(result):
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result
        wait = min(TRIGGER_RECOVERY_INTERVAL_SECONDS, remaining)
        print(
            "  Workflow dispatch intent is pending recovery; retrying the "
            f"same request_id (attempt {attempt + 1}/"
            f"{TRIGGER_RECOVERY_RETRY_LIMIT})"
        )
        time.sleep(wait)
        result = github_actions(*args, project=project, sd=sd)
    return result


__all__ = [
    "TRIGGER_RECOVERY_INTERVAL_SECONDS",
    "TRIGGER_RECOVERY_RETRY_LIMIT",
    "trigger_with_recovery_retries",
]

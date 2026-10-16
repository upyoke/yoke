"""How a spooled relay record describes whether the function itself ran."""

from __future__ import annotations

from typing import Any, Dict

RESPONSE_TIMEOUT_FAILURE_CLASS = "https_response_timeout"


def application_outcome(entry: Dict[str, Any]) -> str:
    """Name what the record knows about the function's own result.

    A response timeout is not a call that never connected: the server accepted
    the envelope and its handler may have committed after the client stopped
    waiting, so the result is unknown rather than unreached.
    """
    succeeded = entry.get("application_succeeded")
    if succeeded is True:
        return "succeeded"
    if succeeded is False:
        return "failed"
    if entry.get("failure_class") == RESPONSE_TIMEOUT_FAILURE_CLASS:
        return "unknown"
    return "not_reached"


__all__ = ["RESPONSE_TIMEOUT_FAILURE_CLASS", "application_outcome"]

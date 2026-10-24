"""Answer a dropped control-plane database connection with a named failure.

A handler whose database connection drops mid-statement raises psycopg's
``OperationalError`` (``consuming input failed: SSL error: unexpected eof``).
Handlers open a fresh connection on every invocation, so a side-effect-free
function is simply invoked once more, inside its read budget. A function that
changes state is never resent: the lost statement may or may not have
committed, so it answers ``control_plane_connection_lost`` and the caller
decides after re-reading. Either path ends in a typed envelope, never a
traceback, on every transport that dispatches in-process.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry

T = TypeVar("T")

CONNECTION_LOST_CODE = "control_plane_connection_lost"


def side_effect_free(entry: RegistryEntry) -> bool:
    """True only when the function declares no side effects."""
    return not entry.side_effects


def retry_dropped_connection(call: Callable[[], T]) -> T:
    """Run *call*, then once more when its database connection dropped."""
    from yoke_core.domain.connected_env_readiness_connector import (
        looks_like_connection_failure,
    )

    try:
        return call()
    except Exception as exc:  # noqa: BLE001 -- only a dropped connection retries
        if not looks_like_connection_failure(exc):
            raise
    return call()


def name_connection_loss(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    invoke: Callable[[RegistryEntry, FunctionCallRequest], Any],
) -> Any:
    """Invoke the handler; a lost control-plane connection becomes a failure."""
    from yoke_core.domain.connected_env_readiness import (
        is_connection_unavailable_error,
    )

    try:
        return invoke(entry, request)
    except Exception as exc:  # noqa: BLE001 -- everything else propagates
        if not is_connection_unavailable_error(exc):
            raise
        return connection_lost_outcome(entry, exc)


def connection_lost_outcome(entry: RegistryEntry, exc: BaseException) -> HandlerOutcome:
    from yoke_core.domain.connected_env_readiness_connector import redact

    detail = f"{type(exc).__name__}: {redact(str(exc).strip())}"
    if side_effect_free(entry):
        what = "on its original and its fresh connection; nothing was written"
    else:
        what = (
            "while it could change state, so it was not resent and the change "
            "may or may not have committed"
        )
    recovery = (
        "Re-read the state this call targets, then rerun the command once "
        "`yoke env list` shows the control plane reachable."
    )
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=CONNECTION_LOST_CODE,
            message=(
                f"{entry.function_id} lost its control-plane database "
                f"connection {what} ({detail})."
            ),
            recovery_hint=recovery,
        ),
    )


__all__ = [
    "CONNECTION_LOST_CODE",
    "connection_lost_outcome",
    "name_connection_loss",
    "retry_dropped_connection",
    "side_effect_free",
]

"""Answer a lock a handler could not take with a named, retryable refusal.

Three database answers mean the same thing to a caller -- another transaction
held what this call needed, and this call's open transaction did not commit --
so each becomes a typed error the caller can retry on instead of a
``handler_exception`` that reads as a real failure:

- ``run_busy``: the deployment run row stayed locked past its bound
  (:class:`~yoke_core.domain.deployment_runs_lock.DeploymentRunBusy`).
- ``lock_timeout``: any other lock wait outlived a ``lock_timeout``.
- ``statement_cancelled``: an operator cancelled the statement
  (``pg_cancel_backend``) or a server timeout ended it.

The mapping sits once in function dispatch, so every transport that dispatches
in-process -- hosted HTTPS, a team server, a local install -- answers the same
code.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.deployment_runs_lock import RUN_BUSY_CODE, DeploymentRunBusy
from yoke_core.domain.yoke_function_registry import RegistryEntry

LOCK_TIMEOUT_CODE = "lock_timeout"
STATEMENT_CANCELLED_CODE = "statement_cancelled"

#: Codes whose call wrote nothing durable in its open transaction and may be
#: repeated once the holder finishes.
RETRYABLE_LOCK_CODES = frozenset(
    {RUN_BUSY_CODE, LOCK_TIMEOUT_CODE, STATEMENT_CANCELLED_CODE}
)

#: Pauses before each repeat of a call refused with one of those codes: 15s,
#: 30s, then 60s capped, six repeats in all (about six minutes) before the
#: caller stops with a named reason. Shared by the deploy driver and the
#: ``yoke watch`` wrappers, so neither piles requests onto a held run.
LOCK_RETRY_DELAYS_SECONDS = (15.0, 30.0, 60.0, 60.0, 60.0, 60.0)

_SQLSTATE_CODES = {"55P03": LOCK_TIMEOUT_CODE, "57014": STATEMENT_CANCELLED_CODE}

_RETRY = (
    "Re-read the state this call targets, then retry the same command once the "
    "holder finishes; the deploy driver and `yoke watch` wrappers retry on their own."
)


def lock_refusal_outcome(entry: RegistryEntry, exc: BaseException) -> HandlerOutcome | None:
    """The named refusal for *exc*, or ``None`` when it is not a lock answer."""
    if isinstance(exc, DeploymentRunBusy):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code=RUN_BUSY_CODE, message=str(exc)),
        )
    code = _SQLSTATE_CODES.get(str(getattr(exc, "sqlstate", "") or ""))
    if code is None:
        return None
    if code == LOCK_TIMEOUT_CODE:
        what = "waited past its lock_timeout for a lock another transaction held"
    else:
        what = (
            "had its statement cancelled by an operator or a server timeout"
        )
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=code,
            message=(
                f"{code}: {entry.function_id} {what} ({detail}); its open "
                "transaction was rolled back."
            ),
            recovery_hint=_RETRY,
        ),
    )


def name_lock_refusal(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    invoke: Callable[[RegistryEntry, FunctionCallRequest], Any],
) -> Any:
    """Invoke the handler; a lock it could not take becomes a named refusal."""
    try:
        return invoke(entry, request)
    except Exception as exc:  # noqa: BLE001 -- everything else propagates
        outcome = lock_refusal_outcome(entry, exc)
        if outcome is None:
            raise
        return outcome


__all__ = [
    "LOCK_RETRY_DELAYS_SECONDS",
    "LOCK_TIMEOUT_CODE",
    "RETRYABLE_LOCK_CODES",
    "STATEMENT_CANCELLED_CODE",
    "lock_refusal_outcome",
    "name_lock_refusal",
]

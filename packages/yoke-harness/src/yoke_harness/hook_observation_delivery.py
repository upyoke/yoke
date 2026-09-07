"""Classify one telemetry delivery failure and say what to do about it.

Telemetry is disposable, but a batch the control plane will never accept
is not merely lost — retried unchanged and forever it becomes a poison
pill at the head of an ordered queue, and every later observation starves
behind it. A permanently rejected batch is therefore dropped rather than
retried, and a transient one is retried a bounded number of times. What
the resident owes either way is a diagnostic that names the status, the
server's rejection code, and the step that fixes it, because the operator
reading the resident log is the only person who can act on it.

The transport already retains that structure on
:class:`BoundedJsonHttpStatusError` with secrets and terminal controls
scrubbed; the queue used to reduce every failure to its exception class
name and drop the rest.
"""

from __future__ import annotations

from dataclasses import dataclass


# A 4xx says the control plane understood the batch and will not take it,
# so resending the same bytes cannot succeed. These two are the exceptions:
# both mean "not now" rather than "not this".
_TRANSIENT_STATUSES = frozenset({408, 429})

# Bounds. Retries stop long before an offline laptop accumulates a day of
# backlog, and the queue length is capped so one unreachable control plane
# can never grow the resident without limit.
MAX_TRANSIENT_ATTEMPTS = 6
BACKOFF_CEILING_SECONDS = 30.0
OBSERVATION_BACKLOG_LIMIT = 512

_RECOVERY_BY_CODE = {
    "HOOK_OBSERVATION_IDENTITY_REQUIRED": (
        "run hooks through `yoke hook evaluate`, which stamps ambient "
        "session identity before the payload is batched"
    ),
    "HOOK_OBSERVATION_SESSION_INVALID": (
        "the stamped session id is not usable as a session; check "
        "`yoke sessions touch` resolves an id on this machine"
    ),
    "HOOK_OBSERVATION_SESSION_DENIED": (
        "the session belongs to another actor; check the active connection "
        "with `yoke env list`"
    ),
    "HOOK_OBSERVATION_PROJECT_DENIED": (
        "the actor cannot see this project; check the active connection "
        "with `yoke env list`"
    ),
    "HOOK_OBSERVATION_NOT_READ_ONLY": (
        "only read-only tool chains are batchable; this is a client defect "
        "worth a field note"
    ),
    "UNSUPPORTED_HOOK_OBSERVATION_SCHEMA": (
        "client and control plane speak different batch schemas; update the "
        "older side"
    ),
    "UNSUPPORTED_HOOK_SCHEMA": (
        "client and control plane speak different hook schemas; update the "
        "older side"
    ),
}
_DEFAULT_PERMANENT_RECOVERY = (
    "the control plane refuses this batch as sent; update the older of the "
    "client or server revision, then file a field note if it persists"
)
_DEFAULT_TRANSIENT_RECOVERY = "retrying; no action needed unless it persists"


@dataclass(frozen=True)
class DeliveryFailure:
    """One delivery attempt's outcome, safe to print."""

    permanent: bool
    status: int
    code: str
    detail: str

    @property
    def recovery(self) -> str:
        if not self.permanent:
            return _DEFAULT_TRANSIENT_RECOVERY
        return _RECOVERY_BY_CODE.get(self.code, _DEFAULT_PERMANENT_RECOVERY)

    def summary(self) -> str:
        """One line naming what happened, never the request or credential."""
        parts = [f"HTTP {self.status}" if self.status else "no HTTP response"]
        if self.code:
            parts.append(self.code)
        if self.detail:
            parts.append(self.detail)
        return "; ".join(parts)


def _error_fields(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return "", ""
    code = error.get("code")
    message = error.get("message")
    return (
        code.strip()[:64] if isinstance(code, str) else "",
        message.strip()[:200] if isinstance(message, str) else "",
    )


def classify_delivery_failure(exc: BaseException) -> DeliveryFailure:
    """Read the transport's retained rejection instead of discarding it."""
    from yoke_cli.transport.bounded_json_http import BoundedJsonHttpStatusError

    if isinstance(exc, BoundedJsonHttpStatusError):
        code, message = _error_fields(exc.payload)
        return DeliveryFailure(
            permanent=(
                400 <= exc.status < 500 and exc.status not in _TRANSIENT_STATUSES
            ),
            status=exc.status,
            code=code,
            detail=message,
            )
    return DeliveryFailure(
        permanent=False,
        status=0,
        code="",
        detail=f"delivery failed ({type(exc).__name__})",
    )


def retry_delay_seconds(attempts: int, base_seconds: float) -> float:
    """Back off geometrically to a ceiling, so a dead endpoint costs little."""
    delay = base_seconds * (2 ** max(0, attempts - 1))
    return min(BACKOFF_CEILING_SECONDS, delay)


def backlog_diagnostic(*, pending: int, oldest_age_seconds: float) -> str:
    """Name the queue depth and head age the operator would otherwise guess."""
    return f"pending={pending} oldest_age_s={oldest_age_seconds:.1f}"


__all__ = [
    "BACKOFF_CEILING_SECONDS",
    "DeliveryFailure",
    "MAX_TRANSIENT_ATTEMPTS",
    "OBSERVATION_BACKLOG_LIMIT",
    "backlog_diagnostic",
    "classify_delivery_failure",
    "retry_delay_seconds",
]

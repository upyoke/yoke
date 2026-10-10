"""Owned clocks in machine-authorization decision context."""

from typing import Any, Mapping

from yoke_contracts.timestamps import format_instant

MACHINE_END_TIMESTAMPS = ("ended_at", "expired_at", "cancelled_at", "canceled_at")
MACHINE_CONTEXT_TIMESTAMPS = (
    *MACHINE_END_TIMESTAMPS,
    "expires_at",
    "occurred_at",
    "withdrawn_at",
)


def machine_context_wire(context: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only declared clock fields; all other context stays opaque."""
    result = dict(context)
    for key in MACHINE_CONTEXT_TIMESTAMPS:
        if key in result and result[key] is not None:
            result[key] = format_instant(result[key])
    return result

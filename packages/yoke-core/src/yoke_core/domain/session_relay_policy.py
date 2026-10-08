"""Product-owned machine-relay cadence and retry policy."""

from yoke_contracts.fleet_policy import (
    RELAY_POLL_SECONDS,
    RELAY_IDLE_AFTER_MINUTES,
    RELAY_IDLE_POLL_MINUTES,
    MAX_WAKE_ATTEMPTS,
)
from yoke_core.domain.session_relay_types import RelayPolicy


def relay_policy() -> RelayPolicy:
    return RelayPolicy(
        poll_seconds=RELAY_POLL_SECONDS,
        idle_after_minutes=RELAY_IDLE_AFTER_MINUTES,
        idle_poll_minutes=RELAY_IDLE_POLL_MINUTES,
        max_wake_attempts=MAX_WAKE_ATTEMPTS,
    )

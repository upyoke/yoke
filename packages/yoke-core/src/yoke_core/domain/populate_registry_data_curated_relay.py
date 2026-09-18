"""Relay-transport event-registry rows.

Split out of :mod:`populate_registry_data_curated` so that module keeps the
authored-row headroom its own regression test requires. These rows describe
HTTPS relay delivery rather than any application outcome, which is why they
group together: their context distinguishes "the call eventually landed"
from "the operation succeeded".
"""

from __future__ import annotations

from typing import Tuple


RELAY_TRANSPORT_EVENTS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    # --- relay transport (spooled machine-side, emitted once a call lands) ---
    (
        "RelayTransportRetrySucceeded",
        "system",
        "relay_transport",
        "cli",
        "An HTTPS relay call needed more than one attempt and then landed; context distinguishes transport delivery from the final application outcome and carries the function, env, and attempt count",
        "INFO",
    ),
    (
        "RelayTransportAttemptsExhausted",
        "system",
        "relay_transport",
        "cli",
        "An HTTPS relay call spent its whole attempt budget without an answer; context carries the function, env, and attempt count, and the session id resolves the harness it ran under",
        "WARN",
    ),
)


__all__ = ["RELAY_TRANSPORT_EVENTS"]

"""Bounded diagnostics for a launch attempt the control plane closes itself.

A relay that reports its own outcome carries the native facts with it. The
closures here are the other half: the server ends an attempt precisely
because nothing was reported, so the only diagnosable facts left are the
ones the control plane can still observe. Recording them at closure is what
separates "the spawn stalled" from "the machine went quiet", which is
otherwise an hour of cross-referencing relay heartbeats against launch
timestamps after the evidence has aged out.

The two answers this builds are the phase the launch reached before it went
silent, and whether the relay holding it was still connected when the
closure ran. Neither guesses at the native outcome: an attempt closed here
stays uncertain, and a late report still overwrites this document with what
actually happened.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_store import marker, parse_time, value
from yoke_core.domain.session_launch_types import LaunchRecord


# The furthest control-plane phase a launch reached, read from the timestamp
# ladder on its own row. Deliberately distinct from the relay adapters'
# ``native_launch_phase`` vocabulary: that names where the native spawn
# stopped and is only knowable to the machine, while this names where the
# control plane last saw the launch and is knowable without the relay.
_PHASE_LADDER = (
    ("awaiting_registration_at", "awaiting_registration"),
    ("launching_at", "launching"),
    ("assigned_at", "assigned"),
)

TRANSPORT_RELAY_CONNECTED = "relay_connected"
TRANSPORT_RELAY_DISCONNECTED = "relay_disconnected"
TRANSPORT_RELAY_UNKNOWN = "relay_unknown"


def launch_phase_reached(launch: LaunchRecord) -> str:
    """Name the furthest phase this launch reached before the server closed it."""
    for column, phase in _PHASE_LADDER:
        if str(getattr(launch, column, "") or "").strip():
            return phase
    return "queued"


def relay_transport_state(conn: Any, *, relay_id: str | None, now: str) -> str:
    """Report whether the relay holding this attempt was still connected.

    A relay past its connection horizon stopped talking to the control plane,
    which is the signature of transport or host turbulence rather than of an
    adapter that tried and failed. A relay still inside its horizon was
    reachable the whole time, so a launch that produced nothing under it
    points at the spawn, not the transport.
    """
    if not str(relay_id or "").strip():
        return TRANSPORT_RELAY_UNKNOWN
    p = marker(conn)
    row = conn.execute(
        f"SELECT connected_until FROM session_relays WHERE relay_id = {p}",
        (relay_id,),
    ).fetchone()
    if row is None:
        return TRANSPORT_RELAY_UNKNOWN
    connected_until = str(value(row, "connected_until", 0) or "").strip()
    if not connected_until:
        return TRANSPORT_RELAY_UNKNOWN
    if parse_time(now) < parse_time(connected_until):
        return TRANSPORT_RELAY_CONNECTED
    return TRANSPORT_RELAY_DISCONNECTED


def closure_evidence(
    conn: Any,
    *,
    launch: LaunchRecord,
    result_code: str,
    closure_reason: str,
    relay_id: str | None,
    machine_id: str | None,
    started_at: str | None,
    now: str,
) -> dict[str, Any]:
    """Render the bounded facts a server-closed attempt can still answer with.

    ``result_code`` is the terminal code callers should also surface on the
    launch row; ``closure_reason`` names which convergence pass ran, so an
    operator can tell a relay batch that expired from a launch lease that ran
    out from a reconciliation an operator asked for.
    """
    document: dict[str, Any] = {
        "result_code": result_code,
        "closure_reason": closure_reason,
        "launch_phase_reached": launch_phase_reached(launch),
        "transport_state": relay_transport_state(conn, relay_id=relay_id, now=now),
    }
    if str(relay_id or "").strip():
        document["relay_id"] = str(relay_id)
    if str(machine_id or "").strip():
        document["machine_id"] = str(machine_id)
    if str(started_at or "").strip():
        document["native_started_at"] = str(started_at)
        elapsed = parse_time(now) - parse_time(str(started_at))
        document["duration_ms"] = max(0, int(elapsed.total_seconds() * 1000))
    return document


def open_attempt(conn: Any, launch_id: str) -> Any:
    """Return the newest attempt still awaiting an outcome, when one exists."""
    p = marker(conn)
    return conn.execute(
        "SELECT attempt_id, relay_id, machine_id, started_at, evidence "
        f"FROM session_launch_attempts WHERE launch_id = {p} "
        "AND completed_at IS NULL ORDER BY attempt_number DESC LIMIT 1",
        (launch_id,),
    ).fetchone()


__all__ = [
    "TRANSPORT_RELAY_CONNECTED",
    "TRANSPORT_RELAY_DISCONNECTED",
    "TRANSPORT_RELAY_UNKNOWN",
    "closure_evidence",
    "launch_phase_reached",
    "open_attempt",
    "relay_transport_state",
]

"""Whether a machine has room for one more worker, and how to say so.

The relay heartbeat carries what the machine measured about itself -- free
memory, load, cores, and the lane cap it resolved from its own settings or
total memory. The control plane pairs that with what it can see that the
machine cannot: every live session registered from there plus every launch
already assigned there and not yet registered. Those are the lanes a new
launch would join, and a launch is refused when they already fill the cap.

A relay that publishes no reading carries no cap. That is an older relay,
not a roomy machine, and the reading says so rather than passing silently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping

from yoke_contracts.machine_config.machine_capacity import (
    CAP_SOURCE_DERIVED,
    CAP_SOURCE_SETTING,
    MAX_WORKER_LANES_KEY,
    format_bytes,
    sanitize_machine_capacity,
)
from yoke_core.domain import db_backend

MACHINE_AT_CAPACITY = "machine_at_capacity"
RELAY_PREDATES_CAPACITY_REASON = "relay_predates_capacity_readings"
IN_FLIGHT_LAUNCH_STATES = ("assigned", "launching", "awaiting_registration")


@dataclass(frozen=True)
class MachineCapacity:
    """One machine's lanes in use against the cap its relay published."""

    machine_id: str
    live_lanes: int
    max_worker_lanes: int | None
    cap_source: str | None
    free_memory_bytes: int | None
    total_memory_bytes: int | None
    load_average_1m: float | None
    core_count: int | None
    observed_at: str | None

    @property
    def at_capacity(self) -> bool:
        return self.max_worker_lanes is not None and (
            self.live_lanes >= self.max_worker_lanes
        )

    @property
    def unreported(self) -> bool:
        return self.max_worker_lanes is None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["at_capacity"] = self.at_capacity
        payload["summary"] = self.summary()
        return payload

    def summary(self) -> str:
        """``lanes 19/12 · free 44 MB · load 31.2 on 18 cores``."""
        if self.unreported:
            return f"lanes {self.live_lanes}/? · capacity unreported ({RELAY_PREDATES_CAPACITY_REASON})"
        load = (
            "unknown" if self.load_average_1m is None else f"{self.load_average_1m:.1f}"
        )
        cores = "?" if self.core_count is None else str(self.core_count)
        return (
            f"lanes {self.live_lanes}/{self.max_worker_lanes} · "
            f"free {format_bytes(self.free_memory_bytes)} · "
            f"load {load} on {cores} cores"
        )

    def cap_origin(self) -> str:
        if self.cap_source == CAP_SOURCE_SETTING:
            return f"cap from {MAX_WORKER_LANES_KEY}"
        if self.cap_source == CAP_SOURCE_DERIVED:
            return (
                f"cap derived from {format_bytes(self.total_memory_bytes)} total memory"
            )
        return "cap unresolved"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _document(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return sanitize_machine_capacity(value)
    try:
        return sanitize_machine_capacity(json.loads(str(value or "")))
    except (TypeError, ValueError):
        return {}


def live_lane_count(conn: Any, *, machine_id: str, now: str) -> int:
    """Sessions running on the machine plus launches still on their way there."""
    p = _marker(conn)
    sessions = conn.execute(
        f"SELECT COUNT(*) FROM harness_sessions WHERE machine_id = {p} "
        "AND ended_at IS NULL",
        (machine_id,),
    ).fetchone()[0]
    states = ",".join(p for _ in IN_FLIGHT_LAUNCH_STATES)
    launches = conn.execute(
        "SELECT COUNT(*) FROM session_launches "
        f"WHERE assigned_machine_id = {p} AND state IN ({states}) "
        f"AND registered_session_id IS NULL AND deadline_at > {p}",
        (machine_id, *IN_FLIGHT_LAUNCH_STATES, now),
    ).fetchone()[0]
    return int(sessions or 0) + int(launches or 0)


def machine_capacity(
    conn: Any,
    *,
    machine_id: str,
    capacity_document: Any,
    now: str,
) -> MachineCapacity:
    """Pair the relay's published reading with the lanes the plane can see."""
    reading = _document(capacity_document)
    return MachineCapacity(
        machine_id=machine_id,
        live_lanes=live_lane_count(conn, machine_id=machine_id, now=now),
        max_worker_lanes=reading.get("max_worker_lanes"),
        cap_source=reading.get("cap_source"),
        free_memory_bytes=reading.get("free_memory_bytes"),
        total_memory_bytes=reading.get("total_memory_bytes"),
        load_average_1m=reading.get("load_average_1m"),
        core_count=reading.get("core_count"),
        observed_at=reading.get("observed_at"),
    )


def capacity_refusal(capacities: Iterable[MachineCapacity]) -> str:
    """Name each full machine with its numbers, then the three ways out."""
    full = [entry for entry in capacities if entry.at_capacity]
    details = (
        "; ".join(
            f"machine {entry.machine_id} is at its lane cap ({entry.summary()}; "
            f"{entry.cap_origin()})"
            for entry in full
        )
        or "every eligible machine is at its lane cap"
    )
    return (
        f"{details}. Recovery: wait for a landing to free a lane, raise "
        f"{MAX_WORKER_LANES_KEY} under settings in ~/.yoke/config.json on that "
        "machine, or pass --machine to place the launch elsewhere"
    )


__all__ = [
    "IN_FLIGHT_LAUNCH_STATES",
    "MACHINE_AT_CAPACITY",
    "MachineCapacity",
    "RELAY_PREDATES_CAPACITY_REASON",
    "capacity_refusal",
    "live_lane_count",
    "machine_capacity",
]

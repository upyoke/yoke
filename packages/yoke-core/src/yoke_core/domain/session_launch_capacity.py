"""Whether a machine has room for one more worker, and how to say so.

The relay heartbeat carries what the machine measured about itself -- free
memory, load, cores, and the lane cap it resolved from its own settings or
total memory. The control plane pairs that with what it can see that the
machine cannot: live workers another session launched plus every such launch
already assigned there and not yet registered. MAIN sessions, interactive or
launched by the operator without a requester session, use no worker lane.
Those are the lanes a new launch would join, and a launch is refused when they
already fill the cap.

A relay that publishes no reading carries no cap. That is an older relay,
not a roomy machine, and the reading says so rather than passing silently.
"""

from __future__ import annotations

from yoke_contracts.timestamps import as_utc, parse_instant, temporal_wire

from yoke_core.domain.db_helpers import instant_parameter

from datetime import datetime

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
    observed_at: datetime | None

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", parse_instant(self.observed_at))

    @property
    def at_capacity(self) -> bool:
        return self.max_worker_lanes is not None and (
            self.live_lanes >= self.max_worker_lanes
        )

    @property
    def unreported(self) -> bool:
        return self.max_worker_lanes is None

    def to_dict(self) -> dict[str, Any]:
        payload = temporal_wire(asdict(self))
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


def _live_lane_rows(conn: Any, now: datetime) -> tuple[str, tuple[Any, ...]]:
    """One population for placement and grouped fleet occupancy."""
    current = as_utc(now)
    p = _marker(conn)
    states = ",".join(p for _ in IN_FLIGHT_LAUNCH_STATES)
    return (
        "SELECT s.machine_id FROM harness_sessions s "
        "WHERE s.ended_at IS NULL AND s.terminated_at IS NULL "
        "AND EXISTS (SELECT 1 FROM session_launches linked "
        "WHERE linked.registered_session_id = s.session_id "
        "AND linked.requester_session_id IS NOT NULL) UNION ALL "
        "SELECT assigned_machine_id AS machine_id FROM session_launches "
        f"WHERE state IN ({states}) AND registered_session_id IS NULL "
        f"AND requester_session_id IS NOT NULL AND deadline_at > {p}",
        (*IN_FLIGHT_LAUNCH_STATES, instant_parameter(conn, current)),
    )


def live_lane_count(conn: Any, *, machine_id: str, now: datetime) -> int:
    """Live launched workers and unregistered launches on one machine."""
    rows, params = _live_lane_rows(conn, now)
    count = conn.execute(
        f"SELECT COUNT(*) FROM ({rows}) lanes WHERE machine_id = {_marker(conn)}",
        (*params, machine_id),
    ).fetchone()[0]
    return int(count or 0)


def live_lane_counts(conn: Any, *, now: datetime) -> dict[str, int]:
    """The same worker population, grouped without one query per machine."""
    population, params = _live_lane_rows(conn, now)
    rows = conn.execute(
        f"SELECT machine_id, COUNT(*) AS n FROM ({population}) lanes GROUP BY machine_id",
        params,
    ).fetchall()
    return {str(row["machine_id"]): int(row["n"]) for row in rows}


def machine_capacity(
    conn: Any,
    *,
    machine_id: str,
    capacity_document: Any,
    now: datetime,
    live_lanes: int | None = None,
) -> MachineCapacity:
    """Pair the relay's published reading with the lanes the plane can see."""
    current = as_utc(now)
    reading = _document(capacity_document)
    return MachineCapacity(
        machine_id=machine_id,
        live_lanes=(
            live_lane_count(conn, machine_id=machine_id, now=current)
            if live_lanes is None
            else live_lanes
        ),
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

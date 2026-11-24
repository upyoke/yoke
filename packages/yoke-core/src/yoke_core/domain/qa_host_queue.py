"""The one queue every Test Machine serves, oldest eligible waiter first.

Every walk that needs a Test Machine waits in one queue, ordered by when it
first queued (``qa_host_set_turns.line_key``). A wait row names one machine
that can serve its waiter. A walk pinned to a machine, resuming on the machine
that holds its state, or waiting for one host of a simultaneous set has one row
per machine it needs. A walk any of several machines can serve (OS/type and
capability tags match, verified) has one row per eligible machine, all sharing
``need_id``. When a machine frees, it is reserved for the oldest waiter with a
row on it (``qa_host_turns.reserve_host_turn``), so a waiter the machine cannot
serve never blocks the waiters behind it.

Once one row of a need is reserved or granted, its sibling rows stop competing
for other machines. Consuming the reservation cancels them; a released
reservation that ends the wait cancels them too, and one returned to
``waiting`` lets them compete again.
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter, query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p

_QUEUE_LOCK = "qa-host-queue"
_ORDER = "ORDER BY w.queued_at, COALESCE(w.qa_plan_execution_id, w.session_id), w.id"
_LIVE_LINE = (
    "FROM qa_test_machine_waits w JOIN harness_sessions s "
    "ON s.session_id=w.session_id "
    "WHERE (w.state='reserved' OR (w.state='waiting' AND s.ended_at IS NULL AND NOT EXISTS ("
    "SELECT 1 FROM qa_test_machine_waits r WHERE r.need_id=w.need_id "
    "AND r.state IN ('reserved','granted'))))"
)


def lock_host_queue(conn: Any) -> None:
    """Serialize every reservation and release decision across the queue."""
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_QUEUE_LOCK,)
        )


def new_need_id() -> str:
    """The shared id of one waiter's alternative machine rows."""
    return str(uuid4())


def queue_waits(conn: Any, *, include_reserved: bool = False) -> list[dict[str, Any]]:
    """Every competing wait row of a live session, in queue order."""
    state_filter = "" if include_reserved else "AND w.state='waiting'"
    return [
        dict(row)
        for row in query_rows(conn, f"SELECT w.* {_LIVE_LINE} {state_filter} {_ORDER}")
    ]


def machine_waiters(conn: Any, test_machine: str) -> list[dict[str, Any]]:
    """The queue's waits *test_machine* can serve, oldest first."""
    rows = query_rows(
        conn,
        f"SELECT w.* {_LIVE_LINE} AND w.state='waiting' AND w.test_machine={_p(conn)} {_ORDER}",
        (test_machine,),
    )
    return [dict(row) for row in rows]


def _waiter(wait: Mapping[str, Any]) -> tuple[str, str]:
    """One waiter's identity in the queue: its place and its owner."""
    owner = wait["qa_plan_execution_id"] or wait["session_id"]
    return format_instant(wait["queued_at"]), str(owner)


def queue_entries(conn: Any) -> list[dict[str, Any]]:
    """The queue as operators read it: one entry per waiter, in order.

    ``waits_for`` is ``any`` for a single need, ``slots`` for several needs
    with alternatives grouped in ``needs``, and ``all`` for a host set.
    """
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    lines: dict[str, list[dict[str, Any]]] = {}
    waits = queue_waits(conn, include_reserved=True)
    for wait in sorted(waits, key=lambda row: row["state"] != "reserved"):
        lines.setdefault(str(wait["test_machine"]), []).append(wait)
    places = {
        str(wait["id"]): (position, len(line))
        for line in lines.values()
        for position, wait in enumerate(line, 1)
    }
    for wait in waits:
        key = _waiter(wait)
        entry = entries.setdefault(
            key,
            {
                "places": {},
                "session_id": str(wait["session_id"]),
                "execution_id": wait["qa_plan_execution_id"],
                "queued_at": key[0],
                "wait_ids": [],
                "test_machines": [],
                "needs": {},
                "waits_for": "all",
            },
        )
        entry["wait_ids"].append(str(wait["id"]))
        machine = str(wait["test_machine"])
        entry["test_machines"].append(machine)
        entry["places"][machine] = places[str(wait["id"])]
        if wait["need_id"]:
            entry["needs"].setdefault(str(wait["need_id"]), []).append(machine)
    for entry in entries.values():
        entry["test_machines"].sort()
        if entry["needs"]:
            entry["waits_for"] = "slots" if len(entry["needs"]) > 1 else "any"
    return list(entries.values())


def waits_for_text(entry: Mapping[str, Any]) -> str:
    """What a queue entry waits for, in one phrase."""
    machines = list(entry["test_machines"])
    if len(machines) == 1:
        return machines[0]
    if entry["waits_for"] == "slots":
        groups = sorted(sorted(hosts) for hosts in entry["needs"].values())
        slots = [hosts[0] if len(hosts) == 1 else f"any of {', '.join(hosts)}" for hosts in groups]
        return "one host per slot: " + "; ".join(slots)
    joined = ", ".join(machines)
    return f"any of {joined}" if entry["waits_for"] == "any" else f"all of {joined}"


def queue_entry(conn: Any, wait_id: str) -> dict[str, Any] | None:
    """The live queue entry containing this wait."""
    return next((e for e in queue_entries(conn) if wait_id in e["wait_ids"]), None)


def position_text(places: Mapping[str, Any]) -> str:
    """Read a walk's place on each host, with any reservation at the front."""

    def ordinal(value: int) -> str:
        suffix = (
            "th"
            if 11 <= value % 100 <= 13
            else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
        )
        return f"{value}{suffix}"

    return ", ".join(
        f"{ordinal(position)} for {machine}"
        for machine, (position, _length) in sorted(places.items())
    )


def settle_need(conn: Any, wait: Mapping[str, Any]) -> None:
    """Cancel the other machine rows of *wait*'s need; its own row settled."""
    if not wait.get("need_id"):
        return
    p = _p(conn)
    conn.execute(
        f"UPDATE qa_test_machine_waits SET state='cancelled',settled_at={p} "
        f"WHERE need_id={p} AND id<>{p} AND state='waiting'",
        (
            instant_parameter(conn, utc_now()),
            str(wait["need_id"]),
            str(wait["id"]),
        ),
    )


__all__ = [
    "lock_host_queue",
    "machine_waiters",
    "new_need_id",
    "queue_entries",
    "queue_entry",
    "position_text",
    "queue_waits",
    "settle_need",
    "waits_for_text",
]

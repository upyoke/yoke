"""Per-machine facts and latches behind the Overview's machine-keyed modules.

Two activation modules answer for a machine rather than for the universe:
whether a machine is connected, and whether a harness has run from it. A
universe is shared by many people and many machines, so a second machine
viewing the same organization must not read the first machine's history
as its own — "claude-code connected 21m ago" with every harness target
green, while it has connected nothing.

Machine identity is read in exactly one place, :func:`read_registered_machines`.
Today a registered machine is a distinct ``machine_id`` seen on
``session_relays`` (which carries the hostname, connected surfaces, and
liveness) or stamped on ``harness_sessions`` (which carries the harnesses
that ran from it). When the machine registry table lands, that function
switches its identity source to the registry row and nothing else changes;
do not build a second machine surface beside it.

The read is scoped to the viewing actor. A universe is shared by an
organization's members, and another member's laptop is not something the
viewer can act on — it is noise at best and a wrong instruction at worst
("next up: open a harness on a box you have never touched"). Relays name
their owner, so the viewer's machines are their own relays plus any machine
that ran their sessions and has no relay at all. Without a bound actor
(a local single-actor universe) every machine is the viewer's.

The latch is monotone per ``(machine_id, module_key)`` in
``overview_machine_activation_facts``: once a machine has been observed
satisfying a module, the row keeps it activated for that machine even if the
signal later disappears. A new machine starts with no rows, so it reads
"next up" on its own account.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from yoke_core.domain import json_helper
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.overview_harness_hook_health import (
    harness_targets,
    session_identities,
)
from yoke_core.domain.schema_common import _table_exists

#: Module keys latched per machine, in activation order.
MACHINE_MODULE_MACHINE_CONNECTED = "finish_installation_wizard"
MACHINE_MODULE_CONNECT_HARNESS = "connect_harness"
MACHINE_MODULE_KEYS: Tuple[str, ...] = (
    MACHINE_MODULE_MACHINE_CONNECTED,
    MACHINE_MODULE_CONNECT_HARNESS,
)

#: A relay the operator revoked names a machine that left the fleet; it
#: stays listed only while harness sessions still attribute work to it.
RELAY_STATE_REVOKED = "revoked"

FACTS_TABLE = "overview_machine_activation_facts"


def _relayed_machine_ids(conn: Any) -> set:
    """Every machine that has a relay, whoever owns it.

    A machine someone else's relay owns is theirs even if the viewer once
    ran a session on it, so this set is what session-only identity defers to.
    """
    if not _table_exists(conn, "session_relays"):
        return set()
    return {
        str(row[0])
        for row in conn.execute("SELECT machine_id FROM session_relays").fetchall()
    }


def _relay_rows(conn: Any, actor_id: Optional[int]) -> Dict[str, Dict[str, Any]]:
    if not _table_exists(conn, "session_relays"):
        return {}
    machines: Dict[str, Dict[str, Any]] = {}
    owned = "" if actor_id is None else "WHERE actor_id = %s "
    params = () if actor_id is None else (actor_id,)
    for row in conn.execute(
        "SELECT machine_id, hostname, surface_versions, first_seen_at, "
        f"last_seen_at, state FROM session_relays {owned}"
        "ORDER BY last_seen_at", params,
    ).fetchall():
        machine_id = str(row[0])
        try:
            surfaces = json_helper.loads_text(row[2] or "{}")
        except ValueError:
            surfaces = {}
        if not isinstance(surfaces, dict):
            surfaces = {}
        current = machines.get(machine_id)
        registered_at = row[3]
        if current is not None and current["registered_at"]:
            registered_at = min(str(current["registered_at"]), str(row[3] or ""))
        # Rows arrive oldest-first, so the newest relay's name and state win.
        machines[machine_id] = {
            "machine_id": machine_id,
            "name": str(row[1] or "") or None,
            "surfaces": sorted(str(key) for key in surfaces),
            "surface_versions": {
                str(key): value for key, value in surfaces.items()
            },
            "registered_at": registered_at,
            "last_seen_at": row[4],
            "relay_state": str(row[5] or ""),
        }
    return machines


def _session_rows(
    conn: Any, actor_id: Optional[int],
) -> Dict[str, List[Sequence[Any]]]:
    """Session identity rows grouped by machine, in the hook-health shape."""
    grouped: Dict[str, List[Sequence[Any]]] = {}
    owned = "" if actor_id is None else "AND actor_id = %s "
    params = () if actor_id is None else (actor_id,)
    for row in conn.execute(
        "SELECT machine_id, executor, COALESCE(executor_surface, ''), "
        "CASE WHEN tool_call_count > 0 OR last_tool_call_at IS NOT NULL "
        "THEN 1 ELSE 0 END, episode_started_at, last_tool_call_at, offered_at "
        f"FROM harness_sessions WHERE machine_id IS NOT NULL {owned}", params,
    ).fetchall():
        grouped.setdefault(str(row[0]), []).append(tuple(row[1:]))
    return grouped


def _harnesses(rows: Iterable[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Each harness (executor + surface) seen on a machine, newest first."""
    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for executor, surface, _fed, _episode, _tool, offered_at in rows:
        key = (str(executor), str(surface or ""))
        entry = latest.setdefault(
            key, {"executor": key[0], "surface": key[1] or None,
                  "sessions": 0, "last_at": None},
        )
        entry["sessions"] += 1
        if offered_at and (entry["last_at"] is None or str(offered_at) > str(entry["last_at"])):
            entry["last_at"] = offered_at
    return sorted(
        latest.values(), key=lambda entry: str(entry["last_at"] or ""), reverse=True,
    )


def read_registered_machines(
    conn: Any,
    reports: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    actor_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """The viewing actor's machines, with the harnesses that ran from each.

    This is the single machine-identity read for the Overview. Identity
    comes from ``session_relays`` and ``harness_sessions.machine_id`` today;
    when the machine registry table lands, swap the identity source here and
    keep the returned shape. ``reports`` are harness machine reports keyed by
    machine, so each machine's hook health reads only its own evidence.
    ``actor_id`` is the viewer; ``None`` means an unscoped universe and lists
    every machine.
    """
    relays = _relay_rows(conn, actor_id)
    sessions = _session_rows(conn, actor_id)
    if actor_id is not None:
        relayed = _relayed_machine_ids(conn)
        sessions = {
            machine_id: rows for machine_id, rows in sessions.items()
            if machine_id in relays or machine_id not in relayed
        }
    stored = list(reports or ())
    machines: List[Dict[str, Any]] = []
    for machine_id in sorted(set(relays) | set(sessions)):
        relay = relays.get(machine_id)
        rows = sessions.get(machine_id, [])
        if relay is not None and relay["relay_state"] == RELAY_STATE_REVOKED and not rows:
            continue
        harnesses = _harnesses(rows)
        first_session = min((str(row[5]) for row in rows if row[5]), default=None)
        last_session = harnesses[0]["last_at"] if harnesses else None
        machines.append({
            "machine_id": machine_id,
            "name": relay["name"] if relay else None,
            "surfaces": relay["surfaces"] if relay else [],
            "relay_state": relay["relay_state"] if relay else None,
            "registered_at": (relay["registered_at"] if relay else None) or first_session,
            "last_seen_at": max(
                (str(value) for value in (
                    relay["last_seen_at"] if relay else None, last_session,
                ) if value),
                default=None,
            ),
            "harnesses": harnesses,
            "connected": (
                {"executor": harnesses[0]["executor"], "at": last_session}
                if harnesses else None
            ),
            "targets": harness_targets(
                session_identities(rows),
                [row for row in stored if row.get("machine_id") == machine_id],
                installed_surfaces=(
                    relay["surface_versions"] if relay else {}
                ),
            ),
        })
    return machines


def latch_machine_activations(
    conn: Any, satisfied: Dict[str, Dict[str, bool]],
) -> Dict[Tuple[str, str], str]:
    """Latch newly satisfied ``(machine, module)`` pairs; return all latches.

    Monotone and idempotent, exactly like the universe latch: an existing row
    is never touched, a satisfied pair missing its row gains one, and nothing
    is deleted.
    """
    latched = {
        (str(row[0]), str(row[1])): row[2]
        for row in conn.execute(
            f"SELECT machine_id, module_key, activated_at FROM {FACTS_TABLE}"
        ).fetchall()
    }
    now = iso8601_now()
    missing = [
        (machine_id, key)
        for machine_id, modules in satisfied.items()
        for key in MACHINE_MODULE_KEYS
        if modules.get(key) and (machine_id, key) not in latched
    ]
    for machine_id, key in missing:
        conn.execute(
            f"INSERT INTO {FACTS_TABLE} (machine_id, module_key, activated_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (machine_id, module_key) DO NOTHING",
            (machine_id, key, now),
        )
        latched[(machine_id, key)] = now
    if missing:
        conn.commit()
    return latched


def machine_module_rows(
    conn: Any, machines: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Latch each machine's module signals and stamp per-machine activation.

    A listed machine is connected by definition; a harness has connected
    from it once any session carries its id.
    """
    satisfied = {
        machine["machine_id"]: {
            MACHINE_MODULE_MACHINE_CONNECTED: True,
            MACHINE_MODULE_CONNECT_HARNESS: bool(machine["harnesses"]),
        }
        for machine in machines
    }
    latched = latch_machine_activations(conn, satisfied)
    rows: List[Dict[str, Any]] = []
    for machine in machines:
        machine_id = machine["machine_id"]
        rows.append({
            **machine,
            "connected_at": latched.get(
                (machine_id, MACHINE_MODULE_MACHINE_CONNECTED),
            ),
            "harness_activated_at": latched.get(
                (machine_id, MACHINE_MODULE_CONNECT_HARNESS),
            ),
        })
    return rows


def every_machine_has_harness(rows: Sequence[Dict[str, Any]]) -> bool:
    """The harness module's own signal: no listed machine is still pending."""
    return bool(rows) and all(row["harness_activated_at"] for row in rows)


__all__ = [
    "FACTS_TABLE",
    "MACHINE_MODULE_CONNECT_HARNESS",
    "MACHINE_MODULE_KEYS",
    "MACHINE_MODULE_MACHINE_CONNECTED",
    "RELAY_STATE_REVOKED",
    "every_machine_has_harness",
    "latch_machine_activations",
    "machine_module_rows",
    "read_registered_machines",
]

"""The one read that answers which machines a launch may place work on.

Placement asks this module a single question per candidate machine: may the
requesting actor use it, and does the actor own it. Ownership matters because
spending a colleague's quota before your own is a cost the requester did not
choose; usability is the hard gate.

Today both answers come from the relay row itself. A relay reaches the
eligible roster only after its own heartbeat proved its owning actor may
operate the advertised project, so any project operator may place work on any
machine already serving that project, and ``session_relays.actor_id`` names
the owner. When per-machine access settings become registry state, this
function is the single place that reads them -- callers ask it, never the
rows behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain import db_backend


@dataclass(frozen=True)
class MachineAccess:
    """One machine's answer: may this actor use it, and does the actor own it."""

    machine_id: str
    may_use: bool
    owned_by_requester: bool
    denial_reason: str | None = None


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[index]


def machine_access(
    conn: Any,
    *,
    actor_id: int,
    machine_ids: Iterable[str],
) -> dict[str, MachineAccess]:
    """Answer usability and ownership for every named machine.

    A machine with no relay row is not usable and says so, rather than being
    silently dropped from placement.
    """
    wanted = tuple(sorted({str(value) for value in machine_ids if str(value)}))
    if not wanted:
        return {}
    marker = _marker(conn)
    placeholders = ",".join(marker for _ in wanted)
    rows = conn.execute(
        "SELECT machine_id, actor_id FROM session_relays "
        f"WHERE machine_id IN ({placeholders})",
        wanted,
    ).fetchall()
    owners: dict[str, set[int]] = {}
    for row in rows:
        machine_id = str(_cell(row, "machine_id", 0))
        try:
            owner = int(_cell(row, "actor_id", 1))
        except (TypeError, ValueError):
            continue
        owners.setdefault(machine_id, set()).add(owner)
    access: dict[str, MachineAccess] = {}
    for machine_id in wanted:
        known = owners.get(machine_id)
        if not known:
            access[machine_id] = MachineAccess(
                machine_id,
                may_use=False,
                owned_by_requester=False,
                denial_reason="machine has no registered relay",
            )
            continue
        access[machine_id] = MachineAccess(
            machine_id,
            may_use=True,
            owned_by_requester=int(actor_id) in known,
        )
    return access


__all__ = ["MachineAccess", "machine_access"]

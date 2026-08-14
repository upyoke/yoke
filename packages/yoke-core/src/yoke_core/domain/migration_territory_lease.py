"""Who owns migration territory for a model, and for how long.

This is *workflow* serialization: it stops a second work item authoring a
migration against the same model while one is already mid-flight. The window
it has to cover is "from starting a migration until it lands", not "while a
command runs", which is why the lease is held past the call that takes it.

That makes it a different lock from the one the boot applier uses. The
applier takes a per-database advisory lock for *execution* correctness — two
servers must not migrate one database at once — and releases it when the
batch ends. Neither lock substitutes for the other, and holding one says
nothing about the other.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_leases import (
    Lease,
    acquire_lease,
    active_lease,
    get_lease,
    heartbeat_lease,
    release_lease,
)
from yoke_core.domain.migration_apply_contract import LEASE_KEY_PREFIX
from yoke_core.domain import db_mutation_profile as dmp

#: Holder name recorded when a caller has no session of its own.
#: ``coordination_leases.session_id`` is NOT NULL, so an anonymous caller has
#: to be named rather than inserted as null.
ANONYMOUS_HOLDER = "rehearse"


def lease_key_for(model_name: str) -> str:
    return f"{LEASE_KEY_PREFIX}{model_name}"


def enter(
    conn: Any,
    *,
    project: str | int,
    model_name: str,
    session_id: Optional[str],
    commit: bool = True,
) -> Lease:
    """Claim migration territory for *model_name*, or reuse an owned claim.

    Re-entering is normal — iterating on a module means rehearsing repeatedly
    — so a lease this same session already holds is reused and heartbeated
    rather than refused. A lease held by anyone else raises ``LeaseHeldError``
    naming the holder, which is the refusal this exists to produce.
    """
    key = lease_key_for(model_name)
    holder = session_id or ANONYMOUS_HOLDER
    held = active_lease(conn, project, key, for_update=True)
    if held is not None and held.session_id == holder:
        return heartbeat_lease(conn, held.id, commit=commit)
    return acquire_lease(conn, project, key, holder, commit=commit)


def leave(conn: Any, lease_id: int, reason: str) -> Lease:
    """Release migration territory and return the settled lease row."""
    release_lease(conn, lease_id, reason)
    return get_lease(conn, lease_id)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _declared_model(raw: Any) -> str | None:
    try:
        payload = raw if isinstance(raw, dict) else json.loads(str(raw))
        profile = dmp.validate(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if profile.get("state") != dmp.STATE_DECLARED:
        return None
    return str(profile["model_name"])


def _session_has_other_model_owner(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
    item_id: int,
    model_name: str,
) -> bool:
    rows = conn.execute(
        "SELECT DISTINCT i.id, i.db_mutation_profile FROM work_claims wc "
        "JOIN items i ON "
        "(wc.target_kind='item' AND wc.item_id=i.id) OR "
        "(wc.target_kind='epic_task' AND wc.epic_id=i.id) "
        f"WHERE wc.session_id={_p(conn)} AND wc.released_at IS NULL "
        f"AND i.project_id={_p(conn)} AND i.id<>{_p(conn)}",
        (session_id, project_id, item_id),
    ).fetchall()
    return any(_declared_model(row[1]) == model_name for row in rows)


def _historical_item_holders(conn: Any, item_id: int) -> set[str]:
    """Return every session that held item/task authority for this item."""
    rows = conn.execute(
        "SELECT DISTINCT session_id FROM work_claims WHERE "
        f"(target_kind='item' AND item_id={_p(conn)}) OR "
        f"(target_kind='epic_task' AND epic_id={_p(conn)})",
        (int(item_id), int(item_id)),
    ).fetchall()
    return {str(row[0]) for row in rows if row[0]}


def release_for_terminal_item(
    conn: Any,
    *,
    item_id: int,
    holder_session_ids: Collection[str],
    target_status: str,
) -> int | None:
    """Release migration territory proven to belong to a terminal item.

    Ownership is established from the item's typed work-claim holders and
    declared migration model. A foreign holder is untouched. If the same
    session still owns another item against that model, its shared territory
    remains held until that owner also reaches a terminal boundary.
    """
    row = conn.execute(
        f"SELECT project_id, db_mutation_profile FROM items WHERE id={_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    model_name = _declared_model(row[1])
    if model_name is None:
        return None
    lease = active_lease(
        conn,
        int(row[0]),
        lease_key_for(model_name),
        for_update=True,
    )
    holders = {
        *(str(value) for value in holder_session_ids),
        *_historical_item_holders(conn, int(item_id)),
    }
    if lease is None or lease.session_id not in holders:
        return None
    if _session_has_other_model_owner(
        conn,
        session_id=lease.session_id,
        project_id=lease.project_id,
        item_id=int(item_id),
        model_name=model_name,
    ):
        return None
    release_lease(
        conn,
        lease.id,
        f"item-terminal:{target_status}",
        commit=False,
    )
    return lease.id


__all__ = [
    "ANONYMOUS_HOLDER",
    "enter",
    "leave",
    "lease_key_for",
    "release_for_terminal_item",
]

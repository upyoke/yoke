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
from yoke_core.domain.coordination_lease_record import OWNER_KIND_ITEM
from yoke_core.domain.coordination_leases import (
    Lease,
    LeaseHeldError,
    acquire_lease,
    active_lease,
    get_lease,
    heartbeat_lease,
    release_lease,
)
from yoke_core.domain.migration_apply_contract import LEASE_KEY_PREFIX
from yoke_core.domain import db_mutation_profile as dmp


def lease_key_for(model_name: str) -> str:
    return f"{LEASE_KEY_PREFIX}{model_name}"


def enter(
    conn: Any,
    *,
    project: str | int,
    model_name: str,
    item_id: int,
    session_id: Optional[str],
    commit: bool = True,
) -> Lease:
    """Claim migration territory for *model_name*, or reuse an owned claim.

    Authority is item-owned so the hold survives session end. Re-entering
    from the same item heartbeats; any other holder raises
    ``LeaseHeldError``.
    """
    key = lease_key_for(model_name)
    registered = session_id or ""
    held = active_lease(conn, project, key, for_update=True)
    if held is not None:
        if (
            held.owner_kind == OWNER_KIND_ITEM
            and held.owner_item_id == int(item_id)
        ):
            return heartbeat_lease(conn, held.id, commit=commit)
        raise _held_as_error(conn, held)
    return acquire_lease(
        conn,
        project,
        key,
        registered,
        owner_kind=OWNER_KIND_ITEM,
        owner_item_id=int(item_id),
        commit=commit,
    )


def _held_as_error(conn: Any, held: Lease) -> LeaseHeldError:
    from yoke_core.domain.coordination_leases import _held_error

    base = _held_error(conn, held)
    message = (
        f"{base} Migration territory is already owned by another lane, so "
        "its migration entry may collide with this one. Coordinate with the "
        "holder or wait; do not retry or proceed around the lease. An old "
        "heartbeat is a signal to escalate to an operator, not permission to "
        "release the lease or continue."
    )
    return type(base)(message, contention=base.contention)


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


def release_for_terminal_item(
    conn: Any,
    *,
    item_id: int,
    holder_session_ids: Collection[str],
    target_status: str,
) -> int | None:
    """Release migration territory owned by this terminal item."""
    del holder_session_ids
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
    if (
        lease is None
        or lease.owner_kind != OWNER_KIND_ITEM
        or lease.owner_item_id != int(item_id)
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
    "enter",
    "leave",
    "lease_key_for",
    "release_for_terminal_item",
]

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

from typing import Any, Optional

from yoke_core.domain.coordination_leases import (
    Lease,
    acquire_lease,
    active_lease,
    get_lease,
    heartbeat_lease,
    release_lease,
)
from yoke_core.domain.migration_apply_contract import LEASE_KEY_PREFIX

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
    held = active_lease(conn, project, key)
    if held is not None and held.session_id == holder:
        return heartbeat_lease(conn, held.id, commit=commit)
    return acquire_lease(conn, project, key, holder, commit=commit)


def leave(conn: Any, lease_id: int, reason: str) -> Lease:
    """Release migration territory and return the settled lease row."""
    release_lease(conn, lease_id, reason)
    return get_lease(conn, lease_id)


__all__ = ["ANONYMOUS_HOLDER", "enter", "leave", "lease_key_for"]

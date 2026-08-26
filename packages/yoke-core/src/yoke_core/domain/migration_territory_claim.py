"""Who owns migration territory for a model, and for how long.

This is *workflow* serialization: it stops a second work item authoring a
migration against the same model while one is already mid-flight. The window
it has to cover is "from starting a migration until it lands", not "while a
command runs", which is why the claim is held past the call that takes it —
and why its kind is sticky, exempt from the stale-session sweep that would
otherwise hand the model to a second lane mid-authorship.

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
from yoke_core.domain.coordination_claims import (
    CoordinationClaim,
    CoordinationClaimHeldError,
    acquire,
    active_claim,
    get_claim,
    heartbeat,
    held_error,
    release,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.work_claim_targets import (
    make_migration_serialization_target,
)
from yoke_core.domain import db_mutation_profile as dmp

ACQUIRE_REASON = "migration-territory"


def enter(
    conn: Any,
    *,
    project: str | int,
    model_name: str,
    item_id: int,
    session_id: Optional[str],
    commit: bool = True,
) -> CoordinationClaim:
    """Claim migration territory for *model_name*, or reuse an owned claim.

    Authority is item-owned so the hold survives session end. Re-entering
    from the same item heartbeats; any other holder raises
    :class:`CoordinationClaimHeldError`.
    """
    target = make_migration_serialization_target(
        resolve_project_id(conn, project), model_name, int(item_id)
    )
    held = active_claim(conn, target, for_update=True)
    if held is not None:
        if held.owner_item_id == int(item_id):
            return heartbeat(conn, held.id, commit=commit)
        raise _held_as_error(conn, held)
    return acquire(
        conn,
        target,
        session_id or "",
        reason=ACQUIRE_REASON,
        commit=commit,
    )


def _held_as_error(conn: Any, held: CoordinationClaim) -> CoordinationClaimHeldError:
    base = held_error(conn, held)
    message = (
        f"{base} Migration territory is already owned by another lane, so "
        "its migration entry may collide with this one. Coordinate with the "
        "holder or wait; do not retry or proceed around the claim. An old "
        "heartbeat is a signal to escalate to an operator, not permission to "
        "release the claim or continue."
    )
    return type(base)(message, contention=base.contention)


def leave(conn: Any, claim_id: int, reason: str) -> CoordinationClaim:
    """Release migration territory and return the settled claim row."""
    release(conn, claim_id, reason)
    return get_claim(conn, claim_id)


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
    claim = active_claim(
        conn,
        make_migration_serialization_target(
            int(row[0]), model_name, int(item_id)
        ),
        for_update=True,
    )
    if claim is None or claim.owner_item_id != int(item_id):
        return None
    release(
        conn,
        claim.id,
        f"item-terminal:{target_status}",
        canonical_reason="completed",
        commit=False,
    )
    return claim.id


__all__ = [
    "ACQUIRE_REASON",
    "enter",
    "leave",
    "release_for_terminal_item",
]

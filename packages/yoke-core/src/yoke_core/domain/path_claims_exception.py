"""No-claim exception variant of path_claims.register.

Sister of :mod:`yoke_core.domain.path_claims` that owns the
``mode='exception'`` branch separately so the lifecycle module stays
under its line budget. The exception variant lands the row in state
``active`` immediately (there is no door lock to acquire when there
is no coverage) and refuses any path_claim_targets.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_owner import (
    OWNER_KIND_ITEM,
    OWNER_KIND_SESSION,
    Owner,
    owner_columns_for_writer,
)
from yoke_core.domain.path_claims import (
    InvalidActor,
    InvalidTargetSet,
    _now,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def register_exception(
    conn: Any,
    *,
    actor_id: int,
    integration_target: str,
    target_ids: Sequence[int],
    exception_reason: Optional[str],
    session_id: Optional[str] = None,
    item_id: Optional[int] = None,
) -> int:
    """Insert a ``mode='exception'`` claim row and return its id.

    Caller has already validated ``actor_id`` against ``actors``.
    Empty ``target_ids`` and non-empty ``exception_reason`` are
    enforced here so a future caller (other than path_claims.register)
    cannot bypass the invariants.
    """
    if list(target_ids):
        raise InvalidTargetSet(
            "mode='exception' must not declare path_claim_targets; "
            "exceptions record a no-claim justification, not coverage"
        )
    if not (exception_reason or "").strip():
        raise InvalidTargetSet(
            "mode='exception' requires a non-empty exception_reason"
        )
    now = _now()
    if item_id is not None:
        owner = Owner(kind=OWNER_KIND_ITEM, item_id=int(item_id))
    elif session_id:
        owner = Owner(kind=OWNER_KIND_SESSION, session_id=str(session_id))
    else:
        raise InvalidTargetSet(
            "mode='exception' requires item_id or session_id so owner_kind "
            "can be determined"
        )
    owner_cols = owner_columns_for_writer(owner)
    p = _p(conn)
    cur = conn.execute(
        f"""INSERT INTO path_claims
           (state, mode, actor_id, session_id, item_id,
            owner_kind, owner_item_id, owner_session_id, owner_work_claim_id,
            registered_by_actor_id, registered_by_session_id,
            integration_target, registered_at, activated_at,
            exception_reason)
           VALUES ('active', 'exception', {p}, {p}, {p}, {p}, {p}, {p}, {p},
                   {p}, {p}, {p}, {p}, {p}, {p})
           RETURNING id""",
        (
            actor_id, session_id, item_id,
            owner_cols["owner_kind"],
            owner_cols["owner_item_id"],
            owner_cols["owner_session_id"],
            owner_cols["owner_work_claim_id"],
            actor_id, session_id,
            integration_target,
            now, now, exception_reason.strip(),
        ),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


__all__ = ["register_exception"]

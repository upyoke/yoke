"""Runtime ownership guard for ``/yoke do``'s resume dispatch.

The guard answers one question before the loop re-dispatches an
item-scoped routed handler: *does this session still own ``YOK-N``,
or is the routed-ownership defense still naming me as the prior owner
inside the recovery window?*

Two `owned=True` shapes:

1. **Self-claim live.** The calling session holds an unreleased
   ``work_claims`` row on the item — the canonical mutex still names us
   as the owner. ``claim_id`` is the live claim row id.
2. **Defense in flight.** The calling session has released its claim
   (e.g. ``readiness-check-blocked``) and the
   :func:`routed_ownership_exclusions` recent-owner defense from Task
   003 still names us as the prior owner inside
   ``session_reactivation_reacquire_window_s``. ``claim_id`` is the
   latest released claim id and ``defense_in_flight`` is True.

When neither shape holds the call returns ``owned=False`` and, when
some other session now holds a live claim on the item,
``holder_session_id`` names that session so callers can render a
diagnosis. The guard is **read-only** — it never releases or transforms
a claim. On ``owned=False`` the ``/yoke do`` loop terminates the chain
step with a structured non-chainable checkpoint; it does NOT call
``release-work-claim`` on a claim the session no longer owns.

The guard reuses
:func:`yoke_core.domain.frontier_recent_owner.routed_ownership_exclusions`
with ``requesting_session_id=None`` so the existing helper's
self-exclusion filter is bypassed — we want to see ourselves as a
prior owner when the routed-ownership defense is what is keeping the
item from being re-routed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import db_backend
from .frontier_recent_owner import routed_ownership_exclusions
from .runtime_settings import get_seconds


@dataclass(frozen=True)
class OwnershipGuardResult:
    """Outcome of :func:`evaluate_ownership_guard`.

    ``owned=True`` -> the loop may proceed with item-scoped dispatch.
    ``owned=False`` -> route ownership shifted; loop must terminate the
    chain step with a non-chainable checkpoint instead of dispatching.
    """

    owned: bool
    holder_session_id: Optional[str]
    claim_id: Optional[int]
    defense_in_flight: bool


def evaluate_ownership_guard(
    conn: Any,
    *,
    session_id: str,
    item_id: int,
) -> OwnershipGuardResult:
    """Return the runtime ownership status for ``session_id`` over ``item_id``.

    See module docstring for the full contract. The function never
    writes to the DB and never raises on missing schema — when the
    minimal claim/session tables are absent the guard falls back to
    ``owned=False`` so the caller short-circuits rather than crashing.
    """
    not_owned = OwnershipGuardResult(
        owned=False, holder_session_id=None,
        claim_id=None, defense_in_flight=False,
    )
    if not session_id or not item_id:
        return not_owned

    # 1. Self-claim live: the canonical mutex still names us as owner.
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT id FROM work_claims "
            f"WHERE session_id = {p} AND target_kind = 'item' "
            f"AND item_id = {p} AND released_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (session_id, int(item_id)),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return not_owned
    if row is not None:
        return OwnershipGuardResult(
            owned=True, holder_session_id=session_id,
            claim_id=int(row[0]), defense_in_flight=False,
        )

    # 2. Defense in flight: recent-owner exclusion still names us as
    #    prior owner. requesting_session_id=None bypasses self-skip so
    #    we see ourselves in the defended-items map.
    window_s = get_seconds("session_reactivation_reacquire_window_s", 300)
    defended = routed_ownership_exclusions(
        conn, window_s=window_s, requesting_session_id=None,
    )
    detail = defended.get(f"YOK-{int(item_id)}")
    if detail is not None and detail.get("prior_owner_session_id") == session_id:
        latest = detail.get("latest_claim_id")
        return OwnershipGuardResult(
            owned=True, holder_session_id=session_id,
            claim_id=int(latest) if latest else None,
            defense_in_flight=True,
        )

    # 3. Not owned. Surface the current live holder for diagnosis.
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        holder_row = conn.execute(
            "SELECT session_id, id FROM work_claims "
            f"WHERE target_kind = 'item' AND item_id = {p} "
            "AND released_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (int(item_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        holder_row = None
    if holder_row is not None:
        return OwnershipGuardResult(
            owned=False,
            holder_session_id=str(holder_row[0]) if holder_row[0] else None,
            claim_id=int(holder_row[1]) if holder_row[1] is not None else None,
            defense_in_flight=False,
        )
    return not_owned


__all__ = ["OwnershipGuardResult", "evaluate_ownership_guard"]

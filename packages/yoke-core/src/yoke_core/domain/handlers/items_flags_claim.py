"""Implicit work-claim scoping for the item coordination-flag verbs.

Sibling of :mod:`items_flags` so the handler module stays under the
350-line authored cap. Owns the acquire-on-behalf-of-the-caller
mechanics and nothing else: the handlers turn a refusal into the
outcome envelope themselves.
"""

from __future__ import annotations

from typing import Optional


class _ClaimRefused(Exception):
    """A different live session holds the item's work claim."""

    def __init__(self, item_ref: str, holder: str) -> None:
        super().__init__(item_ref)
        self.item_ref = item_ref
        self.holder = holder


def _acquire_for_caller(
    item_id: int,
    item_ref: str,
    session_id: str,
    *,
    reason: str = "item flag verb",
) -> Optional[int]:
    """Ensure the caller owns the item claim; return one it acquired.

    Returns the new claim id when this call established the claim (the
    caller must release it), or None when the calling session already
    held it. Raises :class:`_ClaimRefused` when another live session
    holds it.

    The caller's own claim is read first, because ``claim_work``'s
    conflict check excludes the calling session by design: acquiring
    over a claim we already hold would succeed and hand back a claim id
    that is NOT ours to release. Reading first is not racy for that
    question — only this session can create this session's claim. A
    concurrent acquire by anyone else still surfaces from ``claim_work``
    as ``ALREADY_CLAIMED``, which is re-resolved against the live holder
    below.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.sessions_lifecycle_claim import SessionError, claim_work
    from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit
    from yoke_core.domain.work_claim_targets import make_item_target

    with connect() as conn:
        held = get_claim_for_work_unit(conn, item_id=str(item_id)) or {}
        holder = str(held.get("session_id") or "")
        if holder:
            if holder == str(session_id):
                return None
            raise _ClaimRefused(item_ref, holder)
        try:
            row = claim_work(
                conn,
                session_id=session_id,
                target=make_item_target(item_id),
                reason=reason,
            )
        except SessionError as exc:
            if exc.code != "ALREADY_CLAIMED":
                raise
        else:
            return int(row["id"])
        raced = get_claim_for_work_unit(conn, item_id=str(item_id)) or {}
    winner = str(raced.get("session_id") or "")
    if winner and winner == str(session_id):
        return None
    raise _ClaimRefused(item_ref, winner or "an unidentified session")


def _release_acquired(
    claim_id: Optional[int], *, reason: str = "item flag verb complete"
) -> None:
    """Release only a claim this call acquired; never the caller's own."""
    if claim_id is None:
        return
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.sessions_lifecycle_claim import SessionError, release_claim

    try:
        with connect() as conn:
            release_claim(conn, int(claim_id), reason=reason)
    except SessionError:
        # The write already landed; a failed release is not a write failure.
        pass


__all__ = [
    "_ClaimRefused",
    "_acquire_for_caller",
    "_release_acquired",
]

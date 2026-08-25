"""Session-owned strategy-document locks — holding a document without an item.

A coordinator working a strategy document directly holds it here: the row
carries ``owner_kind='session'`` and the holding session, with no work
item. It is the same table, index, and exclusion rule as the Blitz-owned
claim, so one document still has one holder.

The handoff this exists for: hold the document while shaping it, create a
Blitz from it, release the lock, and the worker claims the Blitz. Until
that release, the Blitz cannot be claimed; while a live Blitz executes the
document, the lock cannot be taken.

A lock is session-owned, so it dies with its session: the stale-session
sweep and explicit claim-releasing session end both release it, exactly as
they release work claims, and an abandoned lock never bricks a document.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.strategy_doc_claim_exclusion import live_execution_refusal
from yoke_core.domain.strategy_docs import get_doc
from yoke_core.domain.strategy_execution_state import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    StrategyExecutionLinkError,
    _marker,
    _row,
    active_strategy_doc_claim,
    claim_holder_label,
)


def _require_live_session(conn: Any, session_id: str) -> None:
    marker = _marker(conn)
    row = _row(
        conn.execute(
            f"SELECT ended_at FROM harness_sessions WHERE session_id = {marker}",
            (session_id,),
        )
    )
    if row is None:
        raise StrategyDocClaimAuthorizationError(
            f"session {session_id!r} is not registered"
        )
    if row["ended_at"] is not None:
        raise StrategyDocClaimAuthorizationError(
            f"session {session_id!r} has ended; begin a session before "
            "locking a strategy document"
        )


def acquire_session_doc_claim(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    session_id: str,
    actor_id: Optional[int],
    reason: Optional[str] = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Lock one strategy document for the calling session, with no work item.

    ``reason`` is audit context echoed back on the returned claim; the row
    itself records a reason only when it is released.
    """
    clean_session = str(session_id or "").strip()
    if not clean_session:
        raise StrategyDocClaimAuthorizationError(
            "locking a strategy document requires the calling session id"
        )
    _require_live_session(conn, clean_session)
    get_doc(conn, int(project_id), slug)
    held = active_strategy_doc_claim(conn, project_id=int(project_id), slug=slug)
    if held is not None:
        if (
            str(held["owner_kind"]) == "session"
            and str(held["owner_session_id"]) == clean_session
        ):
            if commit:
                conn.commit()
            return dict(held, acquire_reason=reason)
        raise StrategyDocClaimConflictError(
            f"strategy document {slug!r} is held by {claim_holder_label(held)}"
        )
    blocking = live_execution_refusal(conn, project_id=int(project_id), slug=slug)
    if blocking is not None:
        raise StrategyDocClaimConflictError(blocking)
    marker = _marker(conn)
    inserted = _row(
        conn.execute(
            "INSERT INTO strategy_doc_claims "
            "(project_id, strategy_doc_slug, owner_kind, owner_session_id, "
            "registered_by_actor_id, registered_by_session_id, registered_at) "
            f"VALUES ({marker}, {marker}, 'session', {marker}, "
            f"{marker}, {marker}, {marker}) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (
                int(project_id),
                slug,
                clean_session,
                actor_id,
                clean_session,
                iso8601_now(),
            ),
        )
    )
    if inserted is None:
        winner = active_strategy_doc_claim(
            conn, project_id=int(project_id), slug=slug,
        )
        label = (
            claim_holder_label(winner) if winner is not None else "another holder"
        )
        raise StrategyDocClaimConflictError(
            f"strategy document {slug!r} is held by {label}"
        )
    claim = active_strategy_doc_claim(conn, project_id=int(project_id), slug=slug)
    if commit:
        conn.commit()
    return dict(claim or {}, acquire_reason=reason)


def release_session_doc_claim(
    conn: Any,
    *,
    project_id: int,
    slug: str,
    session_id: str,
    actor_id: Optional[int],
    reason: Optional[str] = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Release this session's own lock on one strategy document."""
    claim = active_strategy_doc_claim(conn, project_id=int(project_id), slug=slug)
    if claim is None or str(claim["owner_kind"]) != "session":
        raise StrategyExecutionLinkError(
            f"strategy document {slug!r} carries no session-owned lock"
        )
    if str(claim["owner_session_id"]) != str(session_id):
        raise StrategyDocClaimAuthorizationError(
            f"strategy document {slug!r} is held by "
            f"{claim_holder_label(claim)}; only that session may release it"
        )
    released = _release_rows(
        conn,
        claim_ids=(int(claim["id"]),),
        session_id=str(session_id),
        actor_id=actor_id,
        reason=reason or "document lock released",
    )
    if not released:
        raise StrategyExecutionLinkError(
            f"strategy document {slug!r} lock is no longer active"
        )
    if commit:
        conn.commit()
    return released[0]


def release_session_doc_claims_for_session(
    conn: Any,
    session_id: str,
    *,
    reason: str = "session ended",
    actor_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Release every document lock a session still holds.

    The caller owns the transaction, matching the work-claim release the
    stale sweep and session end already perform in the same window.
    """
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT id FROM strategy_doc_claims "
        f"WHERE owner_kind = 'session' AND owner_session_id = {marker} "
        "AND released_at IS NULL ORDER BY id",
        (str(session_id),),
    ).fetchall()
    return _release_rows(
        conn,
        claim_ids=tuple(int(dict(row)["id"]) for row in rows),
        session_id=str(session_id),
        actor_id=actor_id,
        reason=reason,
    )


def _release_rows(
    conn: Any,
    *,
    claim_ids: tuple[int, ...],
    session_id: str,
    actor_id: Optional[int],
    reason: str,
) -> list[dict[str, Any]]:
    marker = _marker(conn)
    released_at = iso8601_now()
    released: list[dict[str, Any]] = []
    for claim_id in claim_ids:
        row = _row(
            conn.execute(
                "UPDATE strategy_doc_claims "
                f"SET released_by_actor_id = {marker}, "
                f"released_by_session_id = {marker}, released_at = {marker}, "
                f"release_mode = 'normal', release_reason = {marker} "
                f"WHERE id = {marker} AND released_at IS NULL "
                "RETURNING id, project_id, strategy_doc_slug",
                (actor_id, session_id, released_at, reason, claim_id),
            )
        )
        if row is None:
            continue
        released.append(
            {
                "claim_id": int(row["id"]),
                "project_id": int(row["project_id"]),
                "slug": str(row["strategy_doc_slug"]),
                "owner_kind": "session",
                "owner_session_id": session_id,
                "released_at": released_at,
                "release_mode": "normal",
                "release_reason": reason,
            }
        )
    return released


__all__ = [
    "acquire_session_doc_claim",
    "release_session_doc_claim",
    "release_session_doc_claims_for_session",
]

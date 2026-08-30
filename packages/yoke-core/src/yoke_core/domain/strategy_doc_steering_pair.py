"""Association between a steering seat and its strategy-document lock.

The seat lives on ``work_claims``; the document lock lives on
``strategy_doc_claims``. They meet at read time the same way session
holdings already do: ``owner_kind='session'`` plus ``owner_session_id``
and ``project_id``, with hold windows overlapping for history.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.sessions_holdings_claim_facts import steered_document_slugs
from yoke_core.domain.strategy_execution_state import (
    StrategyDocClaimAuthorizationError,
    _marker,
    _row,
    active_strategy_doc_claim,
    claim_holder_label,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING,
    from_row as work_claim_target_from_row,
    make_steering_target,
)


def active_steering_claim_id(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
) -> Optional[int]:
    """Return this session's live steering seat for the project, if any."""
    marker = _marker(conn)
    target = make_steering_target(int(project_id))
    row = _row(
        conn.execute(
            "SELECT id FROM work_claims "
            f"WHERE target_kind = {marker} AND scope = {marker} "
            f"AND session_id = {marker} AND released_at IS NULL",
            (TARGET_KIND_STEERING, target.scope_json(), str(session_id)),
        )
    )
    return None if row is None else int(row["id"])


def _work_claim_project_id(conn: Any, work_claim_id: int) -> Optional[int]:
    marker = _marker(conn)
    row = _row(
        conn.execute(
            f"SELECT target_kind, scope FROM work_claims WHERE id = {marker}",
            (int(work_claim_id),),
        )
    )
    if row is None:
        return None
    target = work_claim_target_from_row(row)
    if target.kind != TARGET_KIND_STEERING:
        return None
    return int(target.project_id or 0) or None


def active_paired_session_doc_claim(
    conn: Any,
    work_claim_id: int,
) -> Optional[dict[str, Any]]:
    """Return one active session document associated with a steering claim."""
    slugs = steered_document_slugs(conn, (int(work_claim_id),)).get(
        int(work_claim_id), []
    )
    if not slugs:
        return None
    project_id = _work_claim_project_id(conn, work_claim_id)
    if project_id is None:
        return None
    return active_strategy_doc_claim(
        conn,
        project_id=project_id,
        slug=str(slugs[0]),
    )


def paired_document_slug_for_history(
    conn: Any,
    work_claim_id: int,
) -> Optional[str]:
    """Recover a document slug associated with a released steering claim."""
    slugs = steered_document_slugs(conn, (int(work_claim_id),)).get(
        int(work_claim_id), []
    )
    return None if not slugs else str(slugs[-1])


def release_paired_session_doc_claim(
    conn: Any,
    *,
    work_claim_id: int,
    session_id: str,
    actor_id: Optional[int],
    reason: str,
    commit: bool = True,
) -> Optional[dict[str, Any]]:
    """Release active session documents associated with one steering seat."""
    project_id = _work_claim_project_id(conn, work_claim_id)
    if project_id is None:
        return None
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT id, project_id, strategy_doc_slug, owner_session_id "
        "FROM strategy_doc_claims WHERE owner_kind = 'session' "
        f"AND owner_session_id = {marker} AND project_id = {marker} "
        "AND released_at IS NULL ORDER BY id",
        (str(session_id), int(project_id)),
    ).fetchall()
    released: Optional[dict[str, Any]] = None
    released_at = iso8601_now()
    for raw in rows:
        row = dict(raw)
        if str(row["owner_session_id"]) != str(session_id):
            raise StrategyDocClaimAuthorizationError(
                f"steering claim {work_claim_id} is associated with a "
                f"document held by {claim_holder_label(row)}"
            )
        updated = _row(
            conn.execute(
                "UPDATE strategy_doc_claims "
                f"SET released_by_actor_id = {marker}, "
                f"released_by_session_id = {marker}, released_at = {marker}, "
                f"release_mode = 'normal', release_reason = {marker} "
                f"WHERE id = {marker} AND released_at IS NULL "
                "RETURNING id, project_id, strategy_doc_slug",
                (
                    actor_id,
                    str(session_id),
                    released_at,
                    reason,
                    int(row["id"]),
                ),
            )
        )
        if updated is None:
            continue
        released = {
            "claim_id": int(updated["id"]),
            "project_id": int(updated["project_id"]),
            "slug": str(updated["strategy_doc_slug"]),
            "owner_kind": "session",
            "owner_session_id": str(session_id),
            "released_at": released_at,
            "release_mode": "normal",
            "release_reason": reason,
        }
    if commit:
        conn.commit()
    return released


__all__ = [
    "active_paired_session_doc_claim",
    "active_steering_claim_id",
    "paired_document_slug_for_history",
    "release_paired_session_doc_claim",
]

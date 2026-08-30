"""Durable pairing between a steering seat and its strategy-document lock."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now
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
)


def work_claim_is_active(conn: Any, claim_id: int) -> bool:
    marker = _marker(conn)
    row = _row(
        conn.execute(
            f"SELECT id FROM work_claims WHERE id = {marker} AND released_at IS NULL",
            (int(claim_id),),
        )
    )
    return row is not None


def require_steering_pair(
    conn: Any,
    *,
    work_claim_id: int,
    session_id: str,
    project_id: int,
) -> None:
    """Require an active steering claim owned by this session and project."""
    marker = _marker(conn)
    row = _row(
        conn.execute(
            "SELECT session_id, target_kind, scope, released_at "
            f"FROM work_claims WHERE id = {marker}",
            (int(work_claim_id),),
        )
    )
    if row is None or row["released_at"] is not None:
        raise StrategyDocClaimAuthorizationError(
            f"steering claim {work_claim_id} is not active"
        )
    target = work_claim_target_from_row(row)
    if (
        target.kind != TARGET_KIND_STEERING
        or str(row["session_id"]) != session_id
        or int(target.project_id or 0) != int(project_id)
    ):
        raise StrategyDocClaimAuthorizationError(
            f"work claim {work_claim_id} is not this session's steering seat "
            f"for project {project_id}"
        )


def active_paired_session_doc_claim(
    conn: Any,
    work_claim_id: int,
) -> Optional[dict[str, Any]]:
    """Return the active session document linked to a steering claim."""
    marker = _marker(conn)
    row = _row(
        conn.execute(
            "SELECT project_id, strategy_doc_slug FROM strategy_doc_claims "
            f"WHERE paired_work_claim_id = {marker} AND released_at IS NULL",
            (int(work_claim_id),),
        )
    )
    if row is None:
        return None
    return active_strategy_doc_claim(
        conn,
        project_id=int(row["project_id"]),
        slug=str(row["strategy_doc_slug"]),
    )


def paired_document_slug_for_history(
    conn: Any,
    work_claim_id: int,
) -> Optional[str]:
    """Recover the document slug paired with a released steering claim."""
    marker = _marker(conn)
    row = _row(
        conn.execute(
            "SELECT strategy_doc_slug FROM strategy_doc_claims "
            f"WHERE paired_work_claim_id = {marker} ORDER BY id DESC LIMIT 1",
            (int(work_claim_id),),
        )
    )
    return None if row is None else str(row["strategy_doc_slug"])


def release_paired_session_doc_claim(
    conn: Any,
    *,
    work_claim_id: int,
    session_id: str,
    actor_id: Optional[int],
    reason: str,
    commit: bool = True,
) -> Optional[dict[str, Any]]:
    """Release the active document paired with one steering work claim."""
    claim = active_paired_session_doc_claim(conn, work_claim_id)
    if claim is None:
        return None
    if str(claim["owner_session_id"]) != str(session_id):
        raise StrategyDocClaimAuthorizationError(
            f"steering claim {work_claim_id} is paired with a document held "
            f"by {claim_holder_label(claim)}"
        )
    marker = _marker(conn)
    released_at = iso8601_now()
    row = _row(
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
                int(claim["id"]),
            ),
        )
    )
    if commit:
        conn.commit()
    if row is None:
        return None
    return {
        "claim_id": int(row["id"]),
        "project_id": int(row["project_id"]),
        "slug": str(row["strategy_doc_slug"]),
        "owner_kind": "session",
        "owner_session_id": str(session_id),
        "paired_work_claim_id": int(work_claim_id),
        "released_at": released_at,
        "release_mode": "normal",
        "release_reason": reason,
    }


__all__ = [
    "active_paired_session_doc_claim",
    "paired_document_slug_for_history",
    "release_paired_session_doc_claim",
    "require_steering_pair",
    "work_claim_is_active",
]

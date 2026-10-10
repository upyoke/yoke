"""Association between a steering seat and its strategy-document lock.

The seat lives on ``work_claims``; the document lock lives on
``strategy_doc_claims``. They meet at read time the same way session
holdings already do: ``owner_kind='session'`` plus ``owner_session_id``
and ``project_id``, with hold windows overlapping for history.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.sessions_holdings_claim_facts import steered_document_slugs
from yoke_core.domain.strategy_execution_state import (
    StrategyDocClaimAuthorizationError,
    _marker,
    _row,
    claim_holder_label,
)
from yoke_core.domain.work_claim_target_sql import scope_int_sql
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING,
    decode_scope,
    from_row as work_claim_target_from_row,
)


def active_steering_claim_id(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
) -> Optional[int]:
    """Return this session's live steering seat in the project, if any.

    Whole-project and document seats both answer here: the caller is asking
    whether this session already steers something in the project, and a
    document seat does.
    """
    marker = _marker(conn)
    project_scope = scope_int_sql(conn, "scope", "project_id")
    row = _row(
        conn.execute(
            "SELECT id FROM work_claims "
            f"WHERE target_kind = {marker} AND {project_scope} = {marker} "
            f"AND session_id = {marker} AND released_at IS NULL",
            (TARGET_KIND_STEERING, int(project_id), str(session_id)),
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
    return _paired_active_claim(conn, work_claim_id)


def _paired_active_claim(
    conn: Any, work_claim_id: int, *, strict: bool = False
) -> Optional[dict[str, Any]]:
    """Resolve one lock without borrowing another live seat's document."""
    marker = _marker(conn)
    row = _row(
        conn.execute(
            f"SELECT session_id, scope FROM work_claims WHERE id = {marker} "
            "AND target_kind = 'steering' AND released_at IS NULL",
            (int(work_claim_id),),
        )
    )
    if row is None:
        return None
    if not _table_exists(conn, "strategy_doc_claims") or not _column_exists(
        conn, "strategy_doc_claims", "id"
    ):
        return None
    scope = decode_scope(row["scope"])
    project_id = int(scope["project_id"])
    session_id = str(row["session_id"])
    document = scope.get("document")
    if document:
        claim = _row(
            conn.execute(
                "SELECT * FROM strategy_doc_claims "
                f"WHERE project_id = {marker} AND strategy_doc_slug = {marker} "
                "AND released_at IS NULL",
                (project_id, str(document)),
            )
        )
        if (
            claim is None
            or str(claim.get("owner_session_id")) != session_id
            or claim.get("steering_claim_id") != int(work_claim_id)
        ):
            raise StrategyDocClaimAuthorizationError(
                f"steering claim {work_claim_id} has no paired lock on {document}; "
                "reacquire the seat's document lock before releasing the seat"
            )
        return claim
    project_scope = scope_int_sql(conn, "scope", "project_id")
    other_rows = conn.execute(
        "SELECT scope FROM work_claims "
        f"WHERE target_kind = 'steering' AND session_id = {marker} "
        f"AND {project_scope} = {marker} AND released_at IS NULL AND id <> {marker}",
        (session_id, project_id, int(work_claim_id)),
    ).fetchall()
    other_documents = {
        str(value)
        for raw in other_rows
        if (value := decode_scope(dict(raw)["scope"]).get("document"))
    }
    candidates = conn.execute(
        "SELECT * FROM strategy_doc_claims WHERE owner_kind = 'session' "
        f"AND owner_session_id = {marker} AND project_id = {marker} "
        "AND released_at IS NULL ORDER BY id",
        (session_id, project_id),
    ).fetchall()
    paired = [
        dict(raw)
        for raw in candidates
        if dict(raw).get("steering_claim_id") == int(work_claim_id)
    ]
    if paired:
        return paired[0]
    unmatched = [
        dict(raw)
        for raw in candidates
        if str(dict(raw)["strategy_doc_slug"]) not in other_documents
        and dict(raw).get("steering_claim_id") is None
    ]
    if unmatched and strict:
        names = ", ".join(str(row["strategy_doc_slug"]) for row in unmatched)
        raise StrategyDocClaimAuthorizationError(
            f"steering claim {work_claim_id} has unpaired document locks "
            f"({names}); reacquire this seat with --plan-doc SLUG to bind "
            "its standing plan, or release unrelated document locks first"
        )
    return None


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
    claim = _paired_active_claim(conn, work_claim_id, strict=True)
    if claim is None:
        return None
    marker = _marker(conn)
    if str(claim["owner_session_id"]) != str(session_id):
        raise StrategyDocClaimAuthorizationError(
            f"steering claim {work_claim_id} has a document lock held by "
            f"{claim_holder_label(claim)}"
        )
    released_at = utc_now()
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
                instant_parameter(conn, released_at),
                reason,
                int(claim["id"]),
            ),
        )
    )
    if updated is None:
        raise StrategyDocClaimAuthorizationError(
            f"steering claim {work_claim_id}'s document lock changed during release; "
            "retry the steering release"
        )
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

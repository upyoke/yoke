"""Project-serialized steering claims backed by typed work claims."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
from yoke_core.domain import db_backend
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_claim_lifecycle_lock import (
    lock_session_rows_for_claim_lifecycle,
)
from yoke_core.domain.sessions_ended_recovery import session_ended_message
from yoke_core.domain.sessions_lifecycle_claim_events import emit_steering_claimed
from yoke_core.domain.sessions_queries import _now_iso
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING,
    from_row as target_from_row,
    make_steering_target,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _claim_payload(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["id"] = int(payload["id"])
    payload["scope"] = dict(target_from_row(payload).scope)
    return payload


def lock_project(conn: Any, project_id: int) -> None:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT id FROM projects WHERE id = {_p(conn)}{suffix}",
        (int(project_id),),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Project {project_id} not found.")


def _active_rows(conn: Any, project_id: int) -> list[Any]:
    target = make_steering_target(project_id)
    return conn.execute(
        "SELECT * FROM work_claims "
        f"WHERE target_kind = {_p(conn)} AND scope = {_p(conn)} "
        "AND released_at IS NULL ORDER BY claimed_at ASC, id ASC",
        (TARGET_KIND_STEERING, target.scope_json()),
    ).fetchall()


def acquire(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
    reason: Optional[str] = None,
    doc_slug: str = DEFAULT_STEERING_DOC_SLUG,
    actor_id: Optional[int] = None,
) -> dict[str, Any]:
    """Atomically acquire one project's steering seat and document lock."""
    target = make_steering_target(project_id)
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))
    lock_project(conn, int(project_id))

    rows = _active_rows(conn, int(project_id))
    for row in rows:
        payload = _claim_payload(row)
        if payload["session_id"] == session_id:
            payload["document_claim"] = _acquire_document_pair(
                conn,
                claim=payload,
                project_id=int(project_id),
                doc_slug=doc_slug,
                actor_id=actor_id,
                reason=reason,
            )
            conn.commit()
            return payload
    if rows:
        conflict = _claim_payload(rows[0])
        raise SessionError(
            "ALREADY_CLAIMED",
            f"Steering scope for project {int(project_id)} is already held by "
            f"coordinator session '{conflict['session_id']}' "
            f"(claim {conflict['id']}); inspect it with `yoke claims steering "
            f"list --project {int(project_id)} --active-only`.",
        )

    now = _now_iso()
    p = _p(conn)
    inserted = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat, released_at, release_reason) "
        f"VALUES ({p}, {p}, {p}, 'exclusive', {p}, {p}, NULL, NULL) "
        "RETURNING id",
        (session_id, TARGET_KIND_STEERING, target.scope_json(), now, now),
    ).fetchone()
    if inserted is None:
        raise SessionError("CLAIM_FAILED", "Steering claim was not created.")
    claim_id = int(inserted[0])
    from yoke_core.domain.claim_chain_state import record_claim_reason

    record_claim_reason(conn, claim_id=claim_id, reason=reason)
    claim = _claim_payload(
        conn.execute(
            f"SELECT * FROM work_claims WHERE id = {p}",
            (claim_id,),
        ).fetchone()
    )
    claim["document_claim"] = _acquire_document_pair(
        conn,
        claim=claim,
        project_id=int(project_id),
        doc_slug=doc_slug,
        actor_id=actor_id,
        reason=reason,
    )
    conn.commit()
    emit_steering_claimed(session_id, claim_id, target, reason=reason)
    return claim


def _acquire_document_pair(
    conn: Any,
    *,
    claim: dict[str, Any],
    project_id: int,
    doc_slug: str,
    actor_id: Optional[int],
    reason: Optional[str],
) -> dict[str, Any]:
    from yoke_core.domain.strategy_doc_steering_pair import (
        active_paired_session_doc_claim,
    )
    from yoke_core.domain.strategy_docs import StrategyDocMissingError
    from yoke_core.domain.strategy_execution import (
        StrategyDocClaimAuthorizationError,
        StrategyDocClaimConflictError,
        StrategyExecutionError,
        acquire_session_doc_claim,
    )

    current = active_paired_session_doc_claim(conn, int(claim["id"]))
    if current is not None and str(current["strategy_doc_slug"]) != doc_slug:
        conn.rollback()
        raise SessionError(
            "DOCUMENT_MISMATCH",
            f"Steering claim {claim['id']} is already paired with strategy "
            f"document {current['strategy_doc_slug']!r}; release the claim "
            f"before acquiring it with --doc {doc_slug}.",
        )
    try:
        return acquire_session_doc_claim(
            conn,
            project_id=project_id,
            slug=doc_slug,
            session_id=str(claim["session_id"]),
            actor_id=actor_id,
            reason=reason,
            paired_work_claim_id=int(claim["id"]),
            commit=False,
        )
    except StrategyDocClaimConflictError as exc:
        conn.rollback()
        raise SessionError("DOCUMENT_ALREADY_CLAIMED", str(exc)) from exc
    except StrategyDocMissingError as exc:
        conn.rollback()
        raise SessionError("DOCUMENT_NOT_FOUND", str(exc)) from exc
    except (StrategyDocClaimAuthorizationError, StrategyExecutionError) as exc:
        conn.rollback()
        raise SessionError("DOCUMENT_CLAIM_FAILED", str(exc)) from exc


def list_claims(
    conn: Any,
    *,
    project_id: int,
    session_id: Optional[str] = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """List steering claims for one project, optionally narrowed by holder."""
    target = make_steering_target(project_id)
    p = _p(conn)
    clauses = [f"target_kind = {p}", f"scope = {p}"]
    params: list[Any] = [TARGET_KIND_STEERING, target.scope_json()]
    if session_id:
        clauses.append(f"session_id = {p}")
        params.append(str(session_id))
    if active_only:
        clauses.append("released_at IS NULL")
    rows = conn.execute(
        "SELECT * FROM work_claims WHERE "
        + " AND ".join(clauses)
        + " ORDER BY claimed_at DESC, id DESC",
        tuple(params),
    ).fetchall()
    return [_claim_payload(row) for row in rows]


__all__ = ["acquire", "list_claims", "lock_project"]

"""Scope-serialized steering claims backed by typed work claims.

A seat covers either a whole project or one strategy document inside it.
Non-overlapping seats coexist -- two documents in the same project are two
seats -- while a project seat and any document seat inside it are the same
territory and refuse each other.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_claim_lifecycle_lock import (
    lock_session_rows_for_claim_lifecycle,
)
from yoke_core.domain.sessions_ended_recovery import session_ended_message
from yoke_core.domain.sessions_lifecycle_claim_events import emit_steering_claimed
from yoke_core.domain.sessions_queries import _now_iso
from yoke_core.domain.steering_scope_coverage import scopes_overlap
from yoke_core.domain.steering_seat_holder import holder_facts, holder_label
from yoke_core.domain.work_claim_target_sql import scope_int_sql
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING,
    decode_scope,
    encode_scope,
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


def _overlapping_rows(conn: Any, scope: dict[str, Any]) -> list[Any]:
    """Unreleased steering claims whose scope collides with ``scope``.

    The seat invariant is "no two live steering claims with overlapping
    scopes", not "one per project": the project is the outer key, and a
    finer future scope nested inside a held project scope is still the same
    seat's territory. Liveness is deliberately not consulted here -- an
    unreleased claim row holds the scope until it is released or the
    stale-session sweep reclaims it, and letting a second row exist beside
    it would leave the scope with two holders on record.
    """
    rows = conn.execute(
        "SELECT * FROM work_claims "
        f"WHERE target_kind = {_p(conn)} AND released_at IS NULL "
        "ORDER BY claimed_at ASC, id ASC",
        (TARGET_KIND_STEERING,),
    ).fetchall()
    return [
        row for row in rows if scopes_overlap(decode_scope(dict(row)["scope"]), scope)
    ]


def acquire(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
    reason: Optional[str] = None,
    document: Optional[str] = None,
    plan_document: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> dict[str, Any]:
    """Acquire one steering seat, and the document lock it steers with.

    Coverage and authorship are two decisions, not one. ``document``
    narrows the seat to that document's linked items AND locks it, so a
    document seat steers exactly its own work. ``plan_document`` locks a
    document without narrowing anything: the seat covers the whole
    project and is still the only writer of the standing plan it reads.
    Naming neither takes the project-wide seat and locks nothing.
    """
    if document is not None and plan_document is not None and document != plan_document:
        raise SessionError(
            "DOCUMENT_CONFLICT",
            f"a seat narrowed to {document!r} already locks that document; "
            f"drop --plan-doc {plan_document} to steer {document!r}, or drop "
            f"--doc {document} to cover the whole project while holding "
            f"{plan_document!r}.",
        )
    locked_document = document or plan_document
    target = make_steering_target(project_id, document)
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))
    lock_project(conn, int(project_id))

    rows = _overlapping_rows(conn, dict(target.scope))
    for row in rows:
        payload = _claim_payload(row)
        if payload["session_id"] == session_id:
            if payload["scope"] != dict(target.scope):
                raise SessionError(
                    "SCOPE_MISMATCH",
                    f"This session already holds steering scope "
                    f"{encode_scope(payload['scope'])} (claim {payload['id']}), "
                    f"which overlaps {target.scope_json()}; release it with "
                    f"`yoke claims steering release {payload['id']} --reason "
                    "TEXT` before taking the other scope.",
                )
            payload["document_claim"] = _acquire_document_pair(
                conn,
                claim=payload,
                project_id=int(project_id),
                document=locked_document,
                actor_id=actor_id,
                reason=reason,
            )
            handoff = _drain_role_addressed_messages(conn, claim=payload, target=target)
            payload["message_handoff"] = handoff
            conn.commit()
            _emit_drain(session_id, payload, target, handoff)
            return payload
    if rows:
        conflict = _claim_payload(rows[0])
        raise SessionError(
            "ALREADY_CLAIMED",
            f"Steering scope {target.scope_json()} overlaps the live scope "
            f"{encode_scope(conflict['scope'])} already held by "
            f"{holder_label(conn, conflict)} "
            f"(claim {conflict['id']}); ask that holder for the seat, or take "
            "a seat on a different strategy document with `yoke claims "
            f"steering acquire --project {int(project_id)} --doc SLUG`. "
            f"Inspect live seats with `yoke claims steering list --project "
            f"{int(project_id)} --active-only`.",
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
        document=locked_document,
        actor_id=actor_id,
        reason=reason,
    )
    handoff = _drain_role_addressed_messages(conn, claim=claim, target=target)
    claim["message_handoff"] = handoff
    conn.commit()
    emit_steering_claimed(session_id, claim_id, target, reason=reason)
    _emit_drain(session_id, claim, target, handoff)
    return claim


def _drain_role_addressed_messages(
    conn: Any,
    *,
    claim: dict[str, Any],
    target: Any,
) -> dict[str, Any]:
    """Hand this seat every role-addressed message its scope covers."""
    from yoke_core.domain.steering_fleet_report_compose import (
        steering_scope_descriptor,
    )
    from yoke_core.domain.steering_message_drain import drain_to_seat

    scope = dict(claim["scope"])
    return drain_to_seat(
        conn,
        scope=scope,
        project_id=int(target.project_id),
        session_id=str(claim["session_id"]),
        claim_id=int(claim["id"]),
        descriptor=steering_scope_descriptor(conn, scope),
        now=datetime.now(timezone.utc),
    )


def _emit_drain(
    session_id: str,
    claim: dict[str, Any],
    target: Any,
    handoff: dict[str, Any],
) -> None:
    """Record the handoff counts once the drain has committed."""
    if not handoff.get("drained_count"):
        return
    from yoke_core.domain.sessions_lifecycle_claim_events import (
        emit_steering_messages_drained,
    )

    emit_steering_messages_drained(
        session_id,
        int(claim["id"]),
        target,
        drained_count=int(handoff.get("drained_count") or 0),
        parked_count=int(handoff.get("parked_count") or 0),
        stranded_count=int(handoff.get("stranded_count") or 0),
    )


def _acquire_document_pair(
    conn: Any,
    *,
    claim: dict[str, Any],
    project_id: int,
    document: Optional[str],
    actor_id: Optional[int],
    reason: Optional[str],
) -> Optional[dict[str, Any]]:
    """Take the document lock this seat steers with, whatever its scope.

    Re-acquiring the same seat asks for the same lock it already holds, so
    the acquire is idempotent. A seat that names no document at all --
    neither as its scope nor as its standing plan -- locks nothing.
    """
    from yoke_core.domain.strategy_docs import StrategyDocMissingError
    from yoke_core.domain.strategy_execution import (
        StrategyDocClaimAuthorizationError,
        StrategyDocClaimConflictError,
        StrategyExecutionError,
        acquire_session_doc_claim,
    )

    if document is None:
        return None
    try:
        return acquire_session_doc_claim(
            conn,
            project_id=project_id,
            slug=document,
            session_id=str(claim["session_id"]),
            actor_id=actor_id,
            reason=reason,
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
    """List every steering seat in one project, whatever each seat's scope.

    Project-wide and document seats are both this project's seats, so the
    listing matches on the project inside the scope rather than on one exact
    scope object -- otherwise a document seat would be invisible to the
    listing a refusal points at.
    """
    p = _p(conn)
    project_scope = scope_int_sql(conn, "scope", "project_id")
    clauses = [f"target_kind = {p}", f"{project_scope} = {p}"]
    params: list[Any] = [TARGET_KIND_STEERING, int(project_id)]
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
    return [_with_holder_facts(conn, _claim_payload(row)) for row in rows]


def _with_holder_facts(conn: Any, claim: dict[str, Any]) -> dict[str, Any]:
    """Name the person and machine holding a listed seat, not just its session."""
    claim.update(holder_facts(conn, str(claim["session_id"])))
    return claim


def list_session_claims(
    conn: Any,
    *,
    session_id: str,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """List this session's steering claims across every held scope."""
    p = _p(conn)
    clauses = [f"target_kind = {p}", f"session_id = {p}"]
    params: list[Any] = [TARGET_KIND_STEERING, str(session_id)]
    if active_only:
        clauses.append("released_at IS NULL")
    rows = conn.execute(
        "SELECT * FROM work_claims WHERE "
        + " AND ".join(clauses)
        + " ORDER BY claimed_at ASC, id ASC",
        tuple(params),
    ).fetchall()
    return [_claim_payload(row) for row in rows]


__all__ = ["acquire", "list_claims", "list_session_claims", "lock_project"]

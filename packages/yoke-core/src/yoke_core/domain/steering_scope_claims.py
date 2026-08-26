"""Session-owned steering scopes backed by typed ``work_claims`` rows.

The empty strategy-document set means the whole project. Two live scopes
intersect when they name the same project and either side is whole-project,
or when their document sets share a slug. Acquisition serializes on the
project row so the overlap decision and insert are one transaction.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_claim_lifecycle_lock import (
    lock_session_rows_for_claim_lifecycle,
)
from yoke_core.domain.sessions_ended_recovery import session_ended_message
from yoke_core.domain.sessions_lifecycle_claim_events import (
    emit_steering_scope_claimed,
)
from yoke_core.domain.sessions_queries import _now_iso
from yoke_core.domain.strategy_docs import (
    StrategyDocMissingError,
    UnknownStrategyDocError,
    get_doc,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING_SCOPE,
    WorkClaimTarget,
    make_steering_scope_target,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode_slugs(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        decoded = json.loads(raw)
    else:
        decoded = raw
    if not isinstance(decoded, (list, tuple)):
        raise SessionError(
            "INVALID_CLAIM",
            "steering_strategy_doc_slugs must contain a JSON array.",
        )
    return tuple(str(slug) for slug in decoded)


def _claim_payload(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["id"] = int(payload["id"])
    payload["steering_project_id"] = int(payload["steering_project_id"])
    payload["steering_strategy_doc_slugs"] = list(
        _decode_slugs(payload["steering_strategy_doc_slugs"])
    )
    return payload


def scopes_intersect(left: Iterable[str], right: Iterable[str]) -> bool:
    """Return whether two canonical document sets overlap."""
    left_set = frozenset(left)
    right_set = frozenset(right)
    return not left_set or not right_set or bool(left_set & right_set)


def lock_project_scope(conn: Any, project_id: int) -> None:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT id FROM projects WHERE id = {_p(conn)}{suffix}",
        (int(project_id),),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Project {project_id} not found.")


def _validate_strategy_docs(
    conn: Any,
    project_id: int,
    slugs: Sequence[str],
) -> None:
    for slug in slugs:
        try:
            get_doc(conn, int(project_id), slug)
        except (UnknownStrategyDocError, StrategyDocMissingError) as exc:
            raise SessionError("INVALID_CLAIM", str(exc)) from exc


def _active_rows(conn: Any, project_id: int) -> list[Any]:
    return conn.execute(
        "SELECT * FROM work_claims "
        f"WHERE target_kind = 'steering_scope' "
        f"AND steering_project_id = {_p(conn)} AND released_at IS NULL "
        "ORDER BY claimed_at ASC, id ASC",
        (int(project_id),),
    ).fetchall()


def find_intersection(
    rows: Iterable[Any],
    target: WorkClaimTarget,
) -> Optional[dict[str, Any]]:
    """Return the first live row whose scope intersects ``target``."""
    requested = target.steering_strategy_doc_slugs or ()
    for row in rows:
        payload = _claim_payload(row)
        if scopes_intersect(
            requested,
            payload["steering_strategy_doc_slugs"],
        ):
            return payload
    return None


def acquire(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
    strategy_doc_slugs: Sequence[str],
    registered_by_actor_id: int,
    registered_by_session_id: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Acquire one non-intersecting steering scope for a live session."""
    target = make_steering_scope_target(project_id, strategy_doc_slugs)
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))
    lock_project_scope(conn, int(project_id))
    _validate_strategy_docs(
        conn,
        int(project_id),
        target.steering_strategy_doc_slugs or (),
    )

    rows = _active_rows(conn, int(project_id))
    serialized = target.insert_columns()["steering_strategy_doc_slugs"]
    for row in rows:
        payload = _claim_payload(row)
        if (
            payload["session_id"] == session_id
            and json.dumps(
                payload["steering_strategy_doc_slugs"], separators=(",", ":")
            )
            == serialized
        ):
            conn.commit()
            return payload
    conflict = find_intersection(rows, target)
    if conflict is not None:
        raise SessionError(
            "ALREADY_CLAIMED",
            "Steering scope intersects active steering-scope claim "
            f"{conflict['id']} held by session '{conflict['owner_session_id']}'.",
        )

    now = _now_iso()
    p = _p(conn)
    inserted = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, epic_id, task_num, process_key, "
        "conflict_group, steering_project_id, steering_strategy_doc_slugs, "
        "owner_kind, owner_item_id, owner_session_id, owner_work_claim_id, "
        "registered_by_actor_id, registered_by_session_id, claim_type, "
        "claimed_at, last_heartbeat, released_at, release_reason) "
        f"VALUES ({p}, '{TARGET_KIND_STEERING_SCOPE}', NULL, NULL, NULL, NULL, "
        f"NULL, {p}, {p}, 'session', NULL, {p}, NULL, {p}, {p}, "
        f"'exclusive', {p}, {p}, NULL, NULL) RETURNING id",
        (
            session_id,
            int(project_id),
            serialized,
            session_id,
            int(registered_by_actor_id),
            str(registered_by_session_id),
            now,
            now,
        ),
    ).fetchone()
    if inserted is None:
        raise SessionError("CLAIM_FAILED", "Steering-scope claim was not created.")
    claim_id = int(inserted[0])
    from yoke_core.domain.claim_chain_state import record_claim_reason

    record_claim_reason(conn, claim_id=claim_id, reason=reason)
    conn.commit()
    emit_steering_scope_claimed(
        session_id,
        claim_id,
        target,
        reason=reason,
    )
    row = conn.execute(
        f"SELECT * FROM work_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    return _claim_payload(row)


def list_claims(
    conn: Any,
    *,
    project_id: int,
    session_id: Optional[str] = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """List steering claims in one project, optionally narrowed by holder."""
    p = _p(conn)
    clauses = ["target_kind = 'steering_scope'", f"steering_project_id = {p}"]
    params: list[Any] = [int(project_id)]
    if session_id:
        clauses.append(f"owner_session_id = {p}")
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


__all__ = [
    "acquire",
    "find_intersection",
    "list_claims",
    "lock_project_scope",
    "scopes_intersect",
]

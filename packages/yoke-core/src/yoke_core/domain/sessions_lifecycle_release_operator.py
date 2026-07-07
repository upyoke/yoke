"""Operator-override claim release path.

Split out of ``sessions_lifecycle_release.py`` to keep the parent
module under the 350-line hard limit. This module owns the human-only
``operator_override_release_claim`` flow that the
``service-client claim-release`` CLI dispatches to. The flow refuses
invocation from hook contexts and always emits both ``WorkReleased``
and the dedicated ``OperatorClaimOverride`` event so the audit trail
records the human reason verbatim.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_OPERATOR_CLAIM_OVERRIDE, EVENT_WORK_RELEASED, SessionError
from .sessions_queries import _now_iso, normalize_claim_item_id


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def operator_override_release_claim(
    conn: Any,
    item_id: str,
    operator_reason: str,
    *,
    session_id: Optional[str] = None,
    claim_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Human-only override to release a stranded claim."""
    if os.environ.get("YOKE_HOOK_EVENT"):
        raise SessionError(
            "HOOK_CONTEXT",
            "Operator override cannot be invoked from a hook context "
            f"(YOKE_HOOK_EVENT={os.environ['YOKE_HOOK_EVENT']}). "
            "This command is human-only.",
        )

    normalized = normalize_claim_item_id(item_id)
    if not normalized.isdigit():
        raise SessionError(
            "INVALID_ITEM",
            f"operator_override_release_claim requires a numeric item id; "
            f"got {item_id!r}",
        )
    item_id_int = int(normalized)
    now = _now_iso()
    p = _p(conn)

    if claim_id is not None:
        row = conn.execute(
            "SELECT id, session_id, target_kind, item_id, epic_id, task_num, "
            "process_key, released_at "
            f"FROM work_claims WHERE id = {p}",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise SessionError("NOT_FOUND", f"Claim {claim_id} not found.")
        if row["released_at"] is not None:
            raise SessionError(
                "ALREADY_RELEASED",
                f"Claim {claim_id} was already released.",
            )
        found_session_id = row["session_id"]
    else:
        query_parts = [
            "SELECT id, session_id, target_kind, item_id, epic_id, task_num, "
            "process_key, released_at "
            f"FROM work_claims WHERE target_kind='item' AND item_id = {p} "
            "AND released_at IS NULL"
        ]
        params: list = [item_id_int]
        if session_id:
            query_parts.append(f"AND session_id = {p}")
            params.append(session_id)
        query_parts.append("ORDER BY claimed_at DESC, id DESC LIMIT 1")

        row = conn.execute(" ".join(query_parts), params).fetchone()
        if row is None:
            raise SessionError(
                "NOT_FOUND",
                f"No active claim found for item {item_id}"
                + (f" in session {session_id}" if session_id else "")
                + ".",
            )
        found_session_id = row["session_id"]

    found_claim_id = row["id"]

    current_row = conn.execute(
        "SELECT current_item_id, current_item_set_at "
        f"FROM harness_sessions WHERE session_id = {p}",
        (found_session_id,),
    ).fetchone()
    if current_row is not None and current_row["current_item_id"] is not None:
        current = normalize_claim_item_id(str(current_row["current_item_id"]))
        if current == normalized:
            conn.execute(
                "UPDATE harness_sessions SET "
                f"recent_item_id = {p}, recent_item_recorded_at = {p}, "
                "current_item_id = NULL, current_item_set_at = NULL "
                f"WHERE session_id = {p}",
                (current_row["current_item_id"],
                 current_row["current_item_set_at"], found_session_id),
            )

    conn.execute(
        f"UPDATE work_claims SET released_at = {p}, release_reason = 'released' "
        f"WHERE id = {p}",
        (now, found_claim_id),
    )
    # Operator override is a terminal intent — stamp it on the row so the
    # frontier defense reads state, not the WorkReleased envelope.
    from .claim_chain_state import record_release_intent

    record_release_intent(
        conn, claim_id=int(found_claim_id), intent="operator-override",
    )
    conn.commit()

    _sa._emit_session_event(
        EVENT_WORK_RELEASED,
        session_id=found_session_id,
        item_id=normalized,
        task_num=row["task_num"],
        context={
            "claim_id": found_claim_id,
            "release_reason": "released",
            "release_reason_intent": "operator-override",
            "operator_reason": operator_reason,
            "target_kind": row["target_kind"],
        },
    )

    _sa._emit_session_event(
        EVENT_OPERATOR_CLAIM_OVERRIDE,
        session_id=found_session_id,
        item_id=normalized,
        task_num=row["task_num"],
        context={
            "claim_id": found_claim_id,
            "item_id": normalized,
            "session_id": found_session_id,
            "operator_reason": operator_reason,
            "release_reason_intent": "operator-override",
        },
    )

    return {
        "released": True,
        "claim_id": found_claim_id,
        "item_id": normalized,
        "session_id": found_session_id,
        "task_num": row["task_num"],
        "operator_reason": operator_reason,
    }


__all__ = ["operator_override_release_claim"]

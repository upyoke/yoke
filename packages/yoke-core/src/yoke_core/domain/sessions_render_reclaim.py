"""Stale-session reclaim, done cleanup, and claim handoff."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_WORK_HANDED_OFF,
    EVENT_WORK_RELEASED,
    SessionError,
)
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_registry import _get_claim, _get_session
from .sessions_queries import (
    _now_iso,
    _row_to_dict,
    normalize_claim_item_id,
)
from .sessions_render_attribution import clear_current_item, set_current_item
from .sessions_lifecycle_claim_events import emit_reclaimed_work_claim
from .workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from .work_claim_targets import from_row as work_claim_target_from_row
from .workflow_item_binding_validation import (
    WorkflowItemBindingError,
    validate_work_claim_target,
)


def find_stale_sessions(
    conn: Any,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
) -> List[Dict[str, Any]]:
    """Identify sessions whose canonical activity is older than the threshold."""
    from .session_reclaim_activity import latest_activity
    from .session_staleness import activity_is_stale

    rows = conn.execute(
        "SELECT * FROM harness_sessions WHERE ended_at IS NULL",
    ).fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        activity_at = latest_activity(conn, str(d.get("session_id") or ""))
        if not activity_is_stale(
            activity_at,
            executor=d.get("executor"),
            base_ttl_minutes=stale_threshold_minutes,
        ):
            continue
        result.append(d)
    return result


@rollback_workflow_binding_write_errors
def reclaim_stale_session(
    conn: Any,
    session_id: str,
) -> Dict[str, Any]:
    """Release all claims, leases, and document locks from a stale session.

    Claims are released with reason 'reclaimed'.  Emits one ``WorkReclaimed``
    event per released claim with populated ``item_id``/``task_num``.  A
    session-owned document lock dies with its session for the same reason a
    work claim does: an abandoned lock would leave its document unclaimable.
    """
    now = _now_iso()

    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
        )

    # Capture claim details before releasing for per-claim telemetry
    active_claim_rows = conn.execute(
        """SELECT id, session_id, target_kind, item_id, epic_id, task_num,
                  process_key, conflict_group, steering_project_id,
                  steering_strategy_doc_slugs
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()
    lock_work_claims_workflow_bindings(
        conn, (int(claim_row["id"]) for claim_row in active_claim_rows)
    )
    active_claim_rows = conn.execute(
        """SELECT id, session_id, target_kind, item_id, epic_id, task_num,
                  process_key, conflict_group, steering_project_id,
                  steering_strategy_doc_slugs
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()

    clear_current_item(conn, session_id, commit=False)

    released_claim_rows = []
    for claim_row in active_claim_rows:
        cursor = conn.execute(
            "UPDATE work_claims SET released_at = %s, "
            "release_reason = 'reclaimed' "
            "WHERE id = %s AND released_at IS NULL",
            (now, claim_row["id"]),
        )
        if cursor.rowcount:
            released_claim_rows.append(claim_row)
    from .coordination_lease_reclaim import release_for_reclaimed_session
    from .strategy_doc_session_claims import release_session_doc_claims_for_session

    release_for_reclaimed_session(conn, session_id)
    release_session_doc_claims_for_session(conn, session_id, reason="reclaimed")
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (now, session_id),
    )
    conn.commit()

    for claim_row in released_claim_rows:
        emit_reclaimed_work_claim(session_id, claim_row)

    return _get_session(conn, session_id)


@rollback_workflow_binding_write_errors
def release_claims_for_done_item(
    conn: Any,
    item_id: str,
) -> int:
    """Release all unreleased claims on an item that has transitioned to done.

    When an item completes in any session, foreign claims from other sessions
    (e.g., stale offer sessions that never engaged) must be cleaned up.
    Claims reuse the existing ``completed`` release_reason vocabulary to avoid
    expanding the schema enum; the item-done cause remains queryable via
    per-claim ``WorkReleased`` event context.

    Returns the number of claims released.
    """
    now = _now_iso()
    normalized = normalize_claim_item_id(item_id)
    if not normalized.isdigit():
        return 0
    item_id_int = int(normalized)
    lock_item_workflow_bindings(conn, (item_id_int,))

    unreleased = conn.execute(
        """SELECT wc.id, wc.session_id, wc.item_id, wc.task_num
           FROM work_claims wc
           WHERE wc.target_kind='item' AND wc.item_id = %s
             AND wc.released_at IS NULL""",
        (item_id_int,),
    ).fetchall()

    released = 0
    for claim_row in unreleased:
        conn.execute(
            "UPDATE work_claims SET released_at = %s, release_reason = 'completed' WHERE id = %s",
            (now, claim_row["id"]),
        )
        released += 1

        _sa._emit_session_event(
            EVENT_WORK_RELEASED,
            session_id=claim_row["session_id"],
            item_id=str(claim_row["item_id"])
            if claim_row["item_id"] is not None
            else None,
            task_num=claim_row["task_num"],
            context={
                "claim_id": claim_row["id"],
                "release_reason": "completed",
                "cleanup_reason": "item_done",
            },
        )

    conn.commit()
    return released


def _resolve_effective_ttl(
    executor: Optional[str],
    base_ttl_minutes: int,
    overrides: Optional[Dict[str, int]] = None,
) -> int:
    """Return the effective stale-session TTL for an executor."""
    from .sessions_analytics import EXECUTOR_STALE_TTL_OVERRIDES_MINUTES

    if not executor:
        return base_ttl_minutes
    table = overrides if overrides is not None else EXECUTOR_STALE_TTL_OVERRIDES_MINUTES
    executor_key = executor.lower()
    override = table.get(executor_key)
    if override is None:
        if executor_key.startswith("codex-"):
            override = table.get("codex")
        elif executor_key.startswith("claude-"):
            override = table.get("claude-code")
    if override is None:
        return base_ttl_minutes
    return max(override, base_ttl_minutes)


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


@rollback_workflow_binding_write_errors
def handoff_claim(
    conn: Any,
    claim_id: int,
    target_session_id: str,
) -> Dict[str, Any]:
    """Transfer a claim from one session to another.

    Releases the old claim with reason 'handed_off' and creates a new claim
    for the target session.  Returns the new claim record.
    """
    now = _now_iso()

    # Discover the immutable source session without taking the claim lock.
    # The actual claim state is re-read after the canonical
    # session -> item -> claim lock sequence.
    discovered_claim = conn.execute(
        "SELECT * FROM work_claims WHERE id = %s",
        (claim_id,),
    ).fetchone()
    if discovered_claim is None:
        raise SessionError("NOT_FOUND", f"Claim {claim_id} not found.")
    discovered = _row_to_dict(discovered_claim)

    session_rows = lock_session_rows_for_claim_lifecycle(
        conn,
        (str(discovered["session_id"]), target_session_id),
    )
    if target_session_id not in session_rows:
        raise SessionError(
            "NOT_FOUND",
            f"Target session '{target_session_id}' not found.",
        )
    if session_rows[target_session_id] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Target session '{target_session_id}' has already ended.",
        )

    lock_work_claims_workflow_bindings(conn, (claim_id,))
    old_claim = conn.execute(
        "SELECT * FROM work_claims WHERE id = %s",
        (claim_id,),
    ).fetchone()
    if old_claim is None:
        raise SessionError("NOT_FOUND", f"Claim {claim_id} not found.")
    old_dict = _row_to_dict(old_claim)
    if old_dict["released_at"] is not None:
        raise SessionError(
            "ALREADY_RELEASED",
            f"Claim {claim_id} has already been released.",
        )
    try:
        validate_work_claim_target(
            conn,
            work_claim_target_from_row(old_dict),
        )
    except WorkflowItemBindingError as exc:
        raise SessionError("INVALID_CLAIM", str(exc)) from exc

    # Release old claim
    conn.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'handed_off' WHERE id = %s",
        (now, claim_id),
    )

    # Create new claim for target — preserves the typed-target shape from
    # the source row so the handed-off claim satisfies the schema CHECK.
    cursor = conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, item_id, epic_id, task_num,
            process_key, conflict_group, claim_type,
            claimed_at, last_heartbeat, released_at, release_reason)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
           RETURNING id""",
        (
            target_session_id,
            old_dict["target_kind"],
            old_dict["item_id"],
            old_dict["epic_id"],
            old_dict["task_num"],
            old_dict["process_key"],
            old_dict["conflict_group"],
            old_dict["claim_type"],
            now,
            now,
        ),
    )
    clear_current_item(conn, old_dict["session_id"], commit=False)
    if old_dict.get("target_kind") == "item" and old_dict["item_id"] is not None:
        set_current_item(
            conn,
            target_session_id,
            str(old_dict["item_id"]),
            commit=False,
        )
    new_claim_id = int(cursor.fetchone()[0])
    conn.commit()
    item_id_for_event = (
        str(old_dict["item_id"])
        if old_dict.get("target_kind") == "item" and old_dict["item_id"] is not None
        else None
    )

    _sa._emit_session_event(
        EVENT_WORK_HANDED_OFF,
        session_id=old_dict["session_id"],
        item_id=item_id_for_event,
        task_num=old_dict["task_num"],
        context={
            "source_claim_id": claim_id,
            "new_claim_id": new_claim_id,
            "source_session_id": old_dict["session_id"],
            "target_session_id": target_session_id,
            "item_id": item_id_for_event,
            "epic_id": old_dict["epic_id"],
            "task_num": old_dict["task_num"],
            "target_kind": old_dict.get("target_kind"),
            "process_key": old_dict.get("process_key"),
        },
    )

    return _get_claim(conn, new_claim_id)

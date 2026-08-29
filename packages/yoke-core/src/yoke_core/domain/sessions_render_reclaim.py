"""Stale-session reclaim and claim handoff."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_WORK_HANDED_OFF,
    SessionError,
)
from .session_launch_abandonment import settle_and_notify
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_registry import _get_claim, _get_session
from .sessions_queries import _now_iso, _row_to_dict, clear_chain_checkpoint
from .sessions_render_attribution import (
    clear_current_item,
    release_item_focus_if_current,
    set_current_item,
)
from .sessions_lifecycle_claim_events import emit_reclaimed_work_claim
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from .work_claim_targets import from_row as work_claim_target_from_row
from .workflow_item_binding_validation import (
    WorkflowItemBindingError,
    validate_work_claim_target,
)
from yoke_core.domain.work_claim_target_sql import LIVENESS_BOUND_SQL


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
    """Release the liveness-bound claims and locks of a stale session.

    Sticky claim kinds are exempt by design: the migration or remote suite
    they name keeps running after the session goes quiet, so reclaiming
    would hand a live resource to a second holder. Those stay until their
    own work releases them or an operator does.

    Claims are released with reason 'reclaimed'.  Emits one ``WorkReclaimed``
    event per released claim with populated ``item_id``/``task_num``.  A
    session-owned document lock dies with its session for the same reason a
    work claim does: an abandoned lock would leave its document unclaimable.
    The session's chain checkpoint dies with it too: chain budget is a live
    session's to spend, and a reclaimed session's leftover checkpoint would
    keep refusing later end attempts with ``chain_pending``.
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
        f"""SELECT id, session_id, target_kind, scope
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
             AND {LIVENESS_BOUND_SQL}
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()
    lock_work_claims_workflow_bindings(
        conn, (int(claim_row["id"]) for claim_row in active_claim_rows)
    )
    active_claim_rows = conn.execute(
        f"""SELECT id, session_id, target_kind, scope
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
             AND {LIVENESS_BOUND_SQL}
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
    from .strategy_doc_session_claims import release_session_doc_claims_for_session

    release_session_doc_claims_for_session(conn, session_id, reason="reclaimed")
    clear_chain_checkpoint(conn, session_id)
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (now, session_id),
    )
    conn.commit()

    for claim_row in released_claim_rows:
        emit_reclaimed_work_claim(session_id, claim_row)
    settle_and_notify(conn, session_id, end_reason="stale_session_reclaimed")

    return _get_session(conn, session_id)


def _resolve_effective_ttl(
    executor: Optional[str],
    base_ttl_minutes: int,
    overrides: Optional[Dict[str, int]] = None,
) -> int:
    """Return the effective stale-session TTL for an executor."""
    if not executor:
        return base_ttl_minutes
    table = overrides if overrides is not None else {}
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
    old_target = work_claim_target_from_row(old_dict)
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
           (session_id, target_kind, scope, claim_type,
            claimed_at, last_heartbeat, released_at, release_reason)
           VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL)
           RETURNING id""",
        (
            target_session_id,
            old_dict["target_kind"],
            old_dict["scope"],
            old_dict["claim_type"],
            now,
            now,
        ),
    )
    if old_target.kind == "item":
        release_item_focus_if_current(conn, old_dict["session_id"], old_target.item_id)
        set_current_item(
            conn,
            target_session_id,
            str(old_target.item_id),
            commit=False,
        )
    new_claim_id = int(cursor.fetchone()[0])
    conn.commit()
    item_id_for_event = str(old_target.item_id) if old_target.kind == "item" else None

    _sa._emit_session_event(
        EVENT_WORK_HANDED_OFF,
        session_id=old_dict["session_id"],
        item_id=item_id_for_event,
        task_num=old_target.task_num,
        context={
            "source_claim_id": claim_id,
            "new_claim_id": new_claim_id,
            "source_session_id": old_dict["session_id"],
            "target_session_id": target_session_id,
            "item_id": item_id_for_event,
            "scope": dict(old_target.scope),
            "epic_id": old_target.epic_id,
            "task_num": old_target.task_num,
            "target_kind": old_dict.get("target_kind"),
            "process_key": old_target.process_key,
        },
    )

    return _get_claim(conn, new_claim_id)

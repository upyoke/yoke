"""Session end and idle-session cleanup helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from .session_launch_abandonment import settle_and_notify
from .sessions_analytics import (
    EVENT_HARNESS_SESSION_ENDED,
    SessionError,
)
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_lifecycle_destructive_guard import (
    emit_release_claims_branch_event,
    prepare_release_claims_branch,
)
from .sessions_lifecycle_registry import _get_session
from .sessions_orphan_tool_call_sweep import sweep_orphaned_tool_calls
from .sessions_queries import _now_iso
from .sessions_render_attribution import clear_current_item
from .strategy_doc_session_claims import release_session_doc_claims_for_session
from .sessions_render_end_claim_release import (
    emit_session_claim_releases_post_commit,
    release_session_claims_transactional,
)
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.work_claim_target_sql import LIVENESS_BOUND_SQL


@rollback_workflow_binding_write_errors
def end_session(
    conn: Any,
    session_id: str,
    *,
    force: bool = False,
    release_claims: bool = False,
    end_reason: str = "session_ended",
    agent_presence_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """End an explicitly selected session, releasing liveness-bound claims.

    Sticky claims survive; hooks use end_session_if_empty to preserve holdings
    and pending delivery. Caller presence evidence is recorded for audit.
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

    active_claim_rows = conn.execute(
        f"""SELECT id, target_kind, scope
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
             AND {LIVENESS_BOUND_SQL}
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()
    lock_work_claims_workflow_bindings(
        conn,
        (int(claim_row["id"]) for claim_row in active_claim_rows),
    )
    active_claim_rows = conn.execute(
        f"""SELECT id, target_kind, scope
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
             AND {LIVENESS_BOUND_SQL}
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()

    # Active-claim handling:
    #   * ``release_claims`` is True — destructive branch. Releases
    #     all liveness-bound claims and falls through to the normal session-end
    #     commit.
    #   * ``release_claims`` is False — explicit no-flags CLI / loop
    #     cleanup path. Auto-release the session's active liveness-bound claims
    #     with ``release_reason='session_ended'`` via the typed
    #     release path so item, epic_task, and process targets all
    #     use the same semantics and process-owned linked path claims
    #     cascade through the existing release behavior.
    presence_evidence: Optional[Dict[str, Any]] = None
    released_claims: List[Dict[str, Any]] = []
    post_commit_receipts: List[Dict[str, Any]] = []
    destructive_event_context: Optional[Dict[str, Any]] = None
    destructive_released_count = 0
    if active_claim_rows:
        if release_claims:
            presence_evidence, destructive_event_context = (
                prepare_release_claims_branch(
                    conn,
                    session_id,
                    force=force,
                    active_claim_rows=active_claim_rows,
                )
            )
            staged_releases, post_commit_receipts = (
                release_session_claims_transactional(
                    conn,
                    session_id,
                    active_claim_rows=active_claim_rows,
                )
            )
            destructive_released_count = len(staged_releases)
        else:
            released_claims, post_commit_receipts = (
                release_session_claims_transactional(
                    conn,
                    session_id,
                    active_claim_rows=active_claim_rows,
                )
            )

    # No active claims — safe to end. Both branches above release claims
    # for an ending session, so the same destructive sweep reason applies
    # to both — orphan tool-call attribution does not distinguish hook
    # vs. CLI entry beyond the harness's own audit trail.
    if active_claim_rows:
        sweep_orphaned_tool_calls(
            conn,
            session_id=session_id,
            lifecycle_reason="session_end_destructive",
        )
    clear_current_item(conn, session_id, commit=False)
    # A document lock is session authority, so it ends with the session.
    release_session_doc_claims_for_session(conn, session_id)

    # Mark session as ended
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (now, session_id),
    )
    conn.commit()

    if destructive_event_context is not None:
        emit_release_claims_branch_event(
            session_id,
            released_count=destructive_released_count,
            context=destructive_event_context,
        )
    elif released_claims:
        emit_session_claim_releases_post_commit(
            conn,
            session_id,
            released=released_claims,
            post_commit_receipts=post_commit_receipts,
        )

    end_context: Dict[str, Any] = {
        "reason": end_reason,
        "force": force,
    }
    if agent_presence_evidence:
        # The two halves answer different questions — the destructive branch
        # says what the claim-release decision saw, the caller says why the
        # session was ended at all — so keeping only one of them loses the
        # reason. They are merged with the branch's own facts winning any
        # future key collision, because that half is computed here and the
        # caller's is asserted from outside.
        presence_evidence = {
            **dict(agent_presence_evidence),
            **(presence_evidence or {}),
        }
    if presence_evidence is not None:
        end_context["agent_presence_evidence"] = presence_evidence
    if released_claims:
        end_context["released_claims_count"] = len(released_claims)
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_ENDED,
        session_id=session_id,
        context=end_context,
    )
    settle_and_notify(conn, session_id, end_reason=end_reason)

    session_row = _get_session(conn, session_id)
    if released_claims:
        session_row["released_claims"] = released_claims
    return session_row


from .sessions_render_end_if_empty import end_session_if_empty  # noqa: E402,F401

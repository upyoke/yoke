"""Session end and idle-session cleanup helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
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
from .sessions_render_end_chain_pending import (
    chain_pending_state as _chain_pending_state,
)
from .sessions_render_end_claim_release import (
    emit_session_claim_releases_post_commit,
    release_session_claims_transactional,
)
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


@rollback_workflow_binding_write_errors
def end_session(
    conn: Any,
    session_id: str,
    *,
    force: bool = False,
    release_claims: bool = False,
    override_chain_end: bool = False,
    chain_end_rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark a session as ended.

    Sessions with active unreleased claims are protected from termination
    by default. When ``release_claims`` is True, the destructive
    claim-release branch releases every active claim before ending.

    Args:
        conn: Read-write database connection.
        session_id: The session to end.
        force: Legacy bypass flag. This no longer
            bypasses the CHAIN_PENDING guard on its own; the explicit
            ``override_chain_end`` flag plus a non-empty rationale are
            now required to end a session while a chainable checkpoint
            still has budget. ``force`` continues to act as the legacy
            kwarg for non-chain guards and is recorded on the terminal
            event for audit.
        release_claims: When True, release active claims through the
            destructive branch in
            ``sessions_lifecycle_destructive_guard``. The CHAIN_PENDING
            guard above still fails closed first when a chainable
            checkpoint has budget. Hook cleanup paths use
            :func:`end_session_if_empty` instead and leave this False.
        override_chain_end: When True AND ``chain_end_rationale`` is a
            non-empty string, bypass the CHAIN_PENDING guard. The override
            emits ``ChainDeclineOverridden`` with the rationale, checkpoint
            step, max_chain_steps, action, and item_id.
        chain_end_rationale: Operator-supplied rationale that justifies
            the chain-end override. Required when ``override_chain_end``
            is True; ignored when not overriding.

    Raises:
        SessionError("NOT_FOUND"): Session does not exist.
        SessionError("SESSION_ENDED"): Session already ended.
        SessionError("CHAIN_PENDING"): Session has a pending chainable
            checkpoint and the override flag plus rationale were not
            supplied.

    The legacy ``ACTIVE_CLAIM`` rejection no longer fires on the
    no-flags branch: explicit ``session-end`` (CLI / ``/yoke do`` loop
    cleanup) now auto-releases active work-claims with
    ``release_reason='session_ended'`` via
    :func:`release_session_claims`. The CHAIN_PENDING guard above still
    blocks loop exits that have honest budget remaining.
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

    # CHAIN_PENDING guard: a persisted chainable checkpoint with
    # remaining budget is a structural reason to keep the session alive — the
    # loop should re-offer instead of exiting. ``force=True`` alone no longer
    # bypasses the guard; the operator must supply ``override_chain_end=True``
    # AND a non-empty rationale, which is recorded as ChainDeclineOverridden.
    rationale = (chain_end_rationale or "").strip()
    chain_override_authorized = bool(override_chain_end and rationale)
    state = _chain_pending_state(conn, session_id)

    if state.pending and not chain_override_authorized:
        raise SessionError(
            "CHAIN_PENDING",
            f"Session '{session_id}' has a pending chainable checkpoint "
            f"(step {state.step}/{state.max_chain_steps}). Pass "
            "override_chain_end=True with a non-empty chain_end_rationale "
            "to end anyway.",
        )

    active_claim_rows = conn.execute(
        """SELECT id, target_kind, item_id, epic_id, task_num,
                  process_key, conflict_group
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()
    lock_work_claims_workflow_bindings(
        conn,
        (int(claim_row["id"]) for claim_row in active_claim_rows),
    )
    active_claim_rows = conn.execute(
        """SELECT id, target_kind, item_id, epic_id, task_num,
                  process_key, conflict_group
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()

    # Active-claim handling:
    #   * ``release_claims`` is True — destructive branch. Releases
    #     all claims and falls through to the normal session-end
    #     commit; the CHAIN_PENDING guard above has already refused
    #     any chain-pending session without an authorized override.
    #   * ``release_claims`` is False — explicit no-flags CLI / loop
    #     cleanup path. Auto-release the session's active work-claims
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
                    chain_override_authorized=chain_override_authorized,
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

    if state.pending and chain_override_authorized:
        from .scheduler_events import emit_chain_decline_overridden

        emit_chain_decline_overridden(
            session_id=session_id,
            checkpoint_step=state.step,
            max_chain_steps=state.max_chain_steps,
            rationale=rationale,
            action=state.action,
            item_id=state.item_id,
        )
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
        "reason": "session_ended",
        "force": force,
    }
    if chain_override_authorized:
        end_context["chain_override_authorized"] = True
        end_context["chain_end_rationale"] = rationale
    if presence_evidence is not None:
        end_context["agent_presence_evidence"] = presence_evidence
    if released_claims:
        end_context["released_claims_count"] = len(released_claims)
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_ENDED,
        session_id=session_id,
        context=end_context,
    )

    session_row = _get_session(conn, session_id)
    if released_claims:
        session_row["released_claims"] = released_claims
    return session_row


from .sessions_render_end_if_empty import end_session_if_empty  # noqa: E402,F401

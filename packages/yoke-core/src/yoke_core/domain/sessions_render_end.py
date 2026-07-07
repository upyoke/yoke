"""Session end and idle-session cleanup helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from .sessions_analytics import (
    EVENT_HARNESS_SESSION_ENDED,
    SessionError,
)
from .sessions_lifecycle_destructive_guard import handle_release_claims_branch
from .sessions_lifecycle_registry import _get_session
from .sessions_orphan_tool_call_sweep import sweep_orphaned_tool_calls
from .sessions_queries import _now_iso
from .sessions_render_attribution import clear_current_item
from .sessions_render_end_chain_pending import (
    chain_pending_state as _chain_pending_state,
    last_released_at as _last_released_at,
    next_action_command as _next_action_command,
    next_offer_step as _next_offer_step,
)
from .sessions_render_end_claim_release import release_session_claims

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
    by default. When ``release_claims`` is True, the shared
    destructive guard decides whether the SessionEnd signal is transient
    and should be deferred, or permanent and safe to release.

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
        release_claims: When True, evaluate the destructive SessionEnd
            branch. A pending chainable checkpoint preserves claims;
            only permanent signals release claims before ending. The
            Stop hook path leaves this False.
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
        SessionError("TRANSIENT_END_DEFERRED"): ``release_claims=True``
            but the destructive guard refused as transient. Session row
            unchanged; ``HarnessSessionEndDeferred`` already emitted.

    The legacy ``ACTIVE_CLAIM`` rejection no longer fires on the
    no-flags branch: explicit ``session-end`` (CLI / ``/yoke do`` loop
    cleanup) now auto-releases active work-claims with
    ``release_reason='session_ended'`` via
    :func:`release_session_claims`. The CHAIN_PENDING guard above still
    blocks loop exits that have honest budget remaining.
    """
    now = _now_iso()

    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row["ended_at"] is not None:
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

    active_claim_rows = conn.execute(
        """SELECT id, target_kind, item_id, epic_id, task_num,
                  process_key, conflict_group
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()

    # Active-claim handling:
    #   * ``release_claims`` is True — destructive hook path. The
    #     shared destructive guard decides: a transient SessionEnd
    #     (chain-budget remaining) defers; a permanent end releases
    #     and falls through to the normal session-end commit.
    #   * ``release_claims`` is False — explicit no-flags CLI / loop
    #     cleanup path. Auto-release the session's active work-claims
    #     with ``release_reason='session_ended'`` via the typed
    #     release path so item, epic_task, and process targets all
    #     use the same semantics and process-owned linked path claims
    #     cascade through the existing release behavior.
    presence_evidence: Optional[Dict[str, Any]] = None
    released_claims: List[Dict[str, Any]] = []
    if active_claim_rows:
        if release_claims:
            deferred, presence_evidence = handle_release_claims_branch(
                conn,
                session_id,
                force=force,
                active_claim_rows=active_claim_rows,
                chain_override_authorized=chain_override_authorized,
            )
            if deferred:
                # Returning the unchanged row here previously surfaced as
                # CLI success=true, masking a no-op as a genuine end.
                raise SessionError(
                    "TRANSIENT_END_DEFERRED",
                    f"Session '{session_id}' end deferred (transient signal: "
                    "chain budget remaining). Claims remain active; use "
                    "claim-release to free a stranded claim or invoke "
                    "session-end with override_chain_end=True plus a "
                    "rationale to override.",
                )
        else:
            released_claims = release_session_claims(
                conn,
                session_id,
                active_claim_rows=active_claim_rows,
            )

    # No active claims — safe to end. Both branches above release claims
    # for an ending session, so the same destructive sweep reason applies
    # to both — orphan tool-call attribution does not distinguish hook
    # vs. CLI entry beyond the harness's own audit trail.
    if active_claim_rows:
        sweep_orphaned_tool_calls(
            conn, session_id=session_id,
            lifecycle_reason="session_end_destructive",
        )
    clear_current_item(conn, session_id)

    # Mark session as ended
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (now, session_id),
    )
    conn.commit()

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


def end_session_if_empty(
    conn: Any,
    session_id: str,
    *,
    triggered_by: str = "stop-hook",
) -> Dict[str, Any]:
    """End a session only when it has no active unreleased claims AND no chain-pending budget.

    This shared lifecycle primitive lets harness stop/session-end hooks clean up
    idle sessions without breaking ownership continuity. Sessions that still
    hold claims, or whose persisted chain checkpoint is chainable within
    budget, remain active and are reported as skipped.

    Returns a plain dict with a stable status:
      - ``ended`` when the session was closed
      - ``has_claims`` when active claims prevented cleanup
      - ``chain_pending`` when no claims remain but a chainable checkpoint
        still has budget — the loop intentionally released its claim mid-chain
        (e.g. the advance/finalize ``handoff-to-polish`` step); cleanup
        defers and emits ``ChainEndDeferred`` so the next agent turn can
        resume via session-offer
      - ``already_ended`` when the session was already inactive
      - ``not_found`` when the session does not exist
    """
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        return {
            "session_id": session_id,
            "status": "not_found",
            "ended": False,
            "active_claim_count": 0,
        }
    if row["ended_at"] is not None:
        return {
            "session_id": session_id,
            "status": "already_ended",
            "ended": False,
            "active_claim_count": 0,
        }

    claim_count = conn.execute(
        """SELECT COUNT(*) AS cnt
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL""",
        (session_id,),
    ).fetchone()["cnt"]
    if claim_count:
        return {
            "session_id": session_id,
            "status": "has_claims",
            "ended": False,
            "active_claim_count": int(claim_count),
        }

    state = _chain_pending_state(conn, session_id)
    if state.pending:
        from .scheduler_events import emit_chain_end_deferred

        last_release_at = _last_released_at(conn, session_id)
        next_action = _next_action_command(
            conn,
            session_id,
            _next_offer_step(state),
        )

        emit_chain_end_deferred(
            session_id=session_id,
            triggered_by=triggered_by,
            checkpoint_step=state.step,
            max_chain_steps=state.max_chain_steps,
            handler_outcome=state.handler_outcome,
            chainable=state.chainable,
            action=state.action,
            item_id=state.item_id,
            last_release_at=last_release_at,
        )

        return {
            "session_id": session_id,
            "status": "chain_pending",
            "ended": False,
            "active_claim_count": 0,
            "checkpoint_step": state.step,
            "max_chain_steps": state.max_chain_steps,
            "handler_outcome": state.handler_outcome,
            "chainable": state.chainable,
            "action": state.action,
            "item_id": state.item_id,
            "last_release_at": last_release_at,
            "triggered_by": triggered_by,
            "next_action": next_action,
        }

    clear_current_item(conn, session_id)
    now = _now_iso()
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (now, session_id),
    )
    conn.commit()

    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_ENDED,
        session_id=session_id,
        context={"reason": "session_empty_auto_ended"},
    )

    session = _get_session(conn, session_id)
    return {
        "session_id": session_id,
        "status": "ended",
        "ended": True,
        "active_claim_count": 0,
        "session": session,
    }

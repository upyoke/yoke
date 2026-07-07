"""Transaction-safe session-offer ownership flow."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from . import db_backend
from .frontier_compute import _canonical_project_label
from .sessions_analytics import SessionError
from .sessions_lifecycle import _get_session, heartbeat
from .sessions_offer_candidates import acquire_claim_from_candidates
from .sessions_offer_envelope_merge import merge_offer_envelope
from .sessions_offer_lane import (
    anchor_lane_on_row,
    build_offer_envelope,
    emit_lane_override_ignored_event,
    emit_session_offered_event,
)
from .sessions_offer_revalidation import emit_chain_budget_unused_if_remaining
from .sessions_queries import _filter_schedule_for_offer, list_claims_for_session, resolve_harness_capabilities
from .sessions_queries_chain import read_chain_skip_memory

logger = logging.getLogger(__name__)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def session_offer_with_ownership(
    conn: Any,
    *,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    execution_lane: str = "primary",
    caller_supplied_lane: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    supported_paths: Optional[List[str]] = None,
    lane_allowed_paths: Optional[Dict[str, List[str]]] = None,
    step: int = 1,
    project_scope: Optional[List[int]] = None,
    wip_cap: int = 5,
    max_chain_steps: int = 3,
) -> Dict[str, Any]:
    """Transaction-safe session-offer path: require-active-session + heartbeat + schedule + claim.

    This is the single authoritative entry point for both the CLI and HTTP
    session-offer adapters.  It ensures that session validation,
    schedule computation, and claim acquisition happen within one coherent
    flow, eliminating the TOCTOU race where two concurrent sessions both see
    the same item as unclaimed.

    The session MUST already exist (created by harness hooks or ``session-begin``).
    This function does NOT create sessions — it validates, heartbeats, schedules,
    and claims.

    Steps:
        1. Require an already-active session; heartbeat to refresh liveness.
        2. Check for existing active claims -> return ``resume`` info if found.
        3. Compute the schedule via ``scheduler.compute_schedule``.
        4. If the decision would be ``charge``, acquire an exclusive claim
           for the selected item before returning. The candidate walk lives
           in ``sessions_offer_candidates.acquire_claim_from_candidates``.

    Args:
        conn: A **read-write** database connection.
        session_id: Stable session identifier for the offer lifetime.
        executor: Executor identity (e.g., ``claude-code``).
        provider: Model provider (e.g., ``anthropic``).
        model: Model identifier.
        workspace: Absolute workspace path.
        execution_lane: Resolved lane (kept for backward compatibility;
            superseded by the row-anchored value).
        caller_supplied_lane: Raw value the CLI / HTTP caller passed
            via ``--lane`` / request body ``execution_lane``. Used
            **only** for the cross-check warning; never as the
            authoritative lane.
        capabilities: Session capability tags.
        supported_paths: Canonical downstream path names the session can
            execute (e.g., ``["advance", "shepherd"]``). When omitted,
            Yoke core may derive this from the shared registry plus manifest
            limitations.
        lane_allowed_paths: Optional config-backed allowlist of
            ``execution_lane`` -> canonical downstream paths. When provided,
            session offering only claims work the current lane may execute.
        project_scope: List of project ids in scope for this offer. Resolved
            upstream by ``resolve_session_project_scope``; ``None`` is
            normalized to ``[]`` (defensive — production callers always
            pass an explicit list).
        wip_cap: WIP cap for scheduling.

    Returns:
        A dict with keys:
            - ``session``: The session record dict.
            - ``claims``: List of active claim dicts for this session.
            - ``new_claim``: The newly created claim dict (if charge), else None.
            - ``schedule_result``: The raw SchedulerResult for adapter use.
            - ``action_hint``: One of ``resume``, ``charge``, ``no_work``
              indicating what the caller should do with the decision engine.
            - ``authoritative_lane``: Row-anchored ``execution_lane``;
              callers MUST use this for downstream lane-policy work.
    """
    from .scheduler import compute_schedule
    from .session_project_scope import resolve_session_project_scope

    if project_scope is None:
        # Callers that do not pass an explicit scope (typically tests
        # constructing the ownership flow directly) get the resolver's
        # all-projects default, which falls back to ``["yoke"]`` when no
        # ``projects`` table exists.
        scope = resolve_session_project_scope(conn, override=None)
    else:
        scope = list(project_scope)

    # Server-side capability derivation. If Yoke owns a harness
    # manifest for this executor, shared registry truth plus manifest-declared
    # limitations override caller-supplied supported_paths.
    harness_caps = resolve_harness_capabilities(executor, workspace)
    _supported = supported_paths or []
    if harness_caps.get("source") == "shared_registry":
        _supported = harness_caps.get("downstream_paths", [])

    # read the row first so the authoritative ``execution_lane``
    # anchors envelope authorship, the ``HarnessSessionOffered`` event,
    # schedule filtering, and the downstream ``decide_next_action``
    # consumer. Combine the ``ended_at`` existence check with the lane
    # and prior-envelope read so the offer path issues one row read.
    row = conn.execute(
        "SELECT ended_at, execution_lane, offer_envelope "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError(
            "NO_SESSION",
            f"No active session found for '{session_id}'. "
            "Session must be started by harness hook or /yoke do before offering work.",
        )
    if row[0] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has ended. Cannot offer work on an inactive session.",
        )

    anchor = anchor_lane_on_row(
        row_lane=row[1],
        caller_supplied_lane=caller_supplied_lane,
        resolved_lane=execution_lane,
    )
    project_label = _canonical_project_label(conn, scope)
    if anchor.mismatch_payload is not None:
        emit_lane_override_ignored_event(
            session_id=session_id,
            project=project_label,
            payload=anchor.mismatch_payload,
        )
    authoritative_lane = anchor.authoritative_lane

    offer_envelope = build_offer_envelope(
        session_id=session_id,
        executor=executor,
        provider=provider,
        model=model,
        workspace=workspace,
        execution_lane=authoritative_lane,
        capabilities=capabilities,
        step=step,
        supported_paths=_supported,
        max_chain_steps=max_chain_steps,
        project_scope=scope,
    )

    emit_session_offered_event(
        session_id=session_id,
        project=project_label,
        project_scope=scope,
        executor=executor,
        provider=provider,
        model=model,
        workspace=workspace,
        execution_lane=authoritative_lane,
        capabilities=capabilities,
        step=step,
        supported_paths=_supported,
    )

    # Heartbeat to refresh liveness
    session_record = heartbeat(conn, session_id)
    merged_envelope = merge_offer_envelope(row[2], offer_envelope)
    conn.execute(
        f"UPDATE harness_sessions SET offer_envelope = {_p(conn)} "
        f"WHERE session_id = {_p(conn)}",
        (json.dumps(merged_envelope), session_id),
    )
    conn.commit()
    session_record = _get_session(conn, session_id)

    # 2. Check for existing active claims -> resume
    active_claims = list_claims_for_session(conn, session_id, active_only=True)
    if active_claims:
        return {
            "session": session_record,
            "claims": active_claims,
            "new_claim": None,
            "schedule_result": None,
            "action_hint": "resume",
            "supported_paths": _supported,
            "authoritative_lane": authoritative_lane,
        }

    # 3. Compute schedule (reads only — safe on rw connection)
    schedule = compute_schedule(
        conn,
        project_scope=scope,
        wip_cap=wip_cap,
        session_id=session_id,
        workspace=workspace,
    )
    schedule = _filter_schedule_for_offer(
        schedule,
        execution_lane=authoritative_lane,
        supported_paths=_supported,
        lane_allowed_paths=lane_allowed_paths,
    )

    # 4. Walk the candidate set: revalidate pre/post-claim, skip live
    #    conflicts and within-chain memory, emit ``SchedulerOfferSkipped``
    #    so the same item isn't re-offered later in the chain.
    schedule, new_claim = acquire_claim_from_candidates(
        conn,
        session_id=session_id,
        schedule=schedule,
        step=step,
        project_scope=scope,
        wip_cap=wip_cap,
        workspace=workspace,
        authoritative_lane=authoritative_lane,
        supported_paths=_supported,
        lane_allowed_paths=lane_allowed_paths,
    )

    action_hint = "charge" if new_claim else "no_work"
    final_skip_memory = read_chain_skip_memory(conn, session_id)
    terminal_reason: Optional[str] = None
    if action_hint == "no_work":
        terminal_reason = emit_chain_budget_unused_if_remaining(
            session_id=session_id,
            chain_step=step,
            max_chain_steps=max_chain_steps,
            skip_memory=final_skip_memory,
            project=project_label,
        )
    return {
        "session": session_record,
        "claims": [new_claim] if new_claim else [],
        "new_claim": new_claim,
        "schedule_result": schedule,
        "action_hint": action_hint,
        "supported_paths": _supported,
        "chain_skip_memory": final_skip_memory,
        "terminal_reason": terminal_reason,
        "authoritative_lane": authoritative_lane,
    }

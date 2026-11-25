"""Unified stale-session cleanup sweep."""

from __future__ import annotations

import time as _time
from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from . import db_backend
from .session_automatic_reclaim import automatic_reclaim, reclaim_facts
from .session_qa_execution_holdings import session_owns_live_qa_execution
from .session_reclaim_activity import (
    REASON_ACTIVE_WORK_CLAIM,
    REASON_KEEPALIVE_HELD,
    REASON_LIVE_QA_EXECUTION,
    REASON_WAKE_DELIVERY_IN_FLIGHT,
    SCOPE_SESSION_CLEANUP,
    classify_reclaimable,
    read_activity_signals,
)
from .session_reclaim_evidence import ReclaimClassification
from .session_cleanup_holdings import session_has_active_work_claim
from .schema_common import _get_columns as _schema_get_columns
from .session_staleness import activity_is_stale
from .time_parse import age_minutes_since
from .sessions_analytics import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_HARNESS_SESSION_STALE_RECLAIMED,
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    EVENT_RECLAIM_ABORTED,
    SessionError,
)
from .sessions_queries import _now_iso
from yoke_contracts.timestamps import utc_now
from .sessions_render_end_chain_pending import chain_pending_state
from .sessions_render import reclaim_stale_session
from .scratch_auto_prune import ScratchPruneResult, auto_prune_stale_scratch
from .session_cleanup_receipt import sweep_receipt
from .sessions_render_end_if_empty import deployment_driver_holds


def clean_stale_harness_sessions(
    conn: Any,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    progress_threshold_minutes: int = DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    *,
    executor_ttl_overrides: Optional[Dict[str, int]] = None,
    project_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Unified stale-session cleanup.

    The short TTL applies to empty sessions. A strategy-document lock uses
    the holdings TTL. An active work claim protects its session until an
    explicit release or terminal action, independent of activity or process.

    Each reclaim emits exactly one ``HarnessSessionStaleReclaimed`` event with
    ``stale_minutes``, ``last_event_at``, ``released_claim_count``, ``executor``,
    and ``reason`` so the ledger has a single canonical entry per cleanup
    event.  Per-claim ``WorkReclaimed`` events are still emitted by
    ``reclaim_stale_session`` for audit continuity.

    The returned buckets are the literal dict built at the end of this
    function; read that rather than a second copy of its keys here.
    """
    _sweep_start = _time.monotonic()

    active_cols = set(_schema_get_columns(conn, "harness_sessions"))
    select_cols = "session_id, offered_at"
    for name in (
        "executor",
        "org_id",
        "last_tool_call_at",
        "tool_call_count",
        "episode_started_at",
        "turn_posture",
        "terminated_at",
    ):
        if name in active_cols:
            select_cols += f", {name}"

    live_where = "ended_at IS NULL"
    if "terminated_at" in active_cols:
        live_where += " AND terminated_at IS NULL"

    if project_ids is None:
        all_active = conn.execute(
            f"SELECT {select_cols} FROM harness_sessions WHERE {live_where}",
        ).fetchall()
    else:
        scoped_project_ids = sorted({int(value) for value in project_ids})
        if scoped_project_ids:
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            placeholders = ", ".join(marker for _ in scoped_project_ids)
            all_active = conn.execute(
                f"SELECT {select_cols} FROM harness_sessions "
                f"WHERE {live_where} "
                f"AND project_id IN ({placeholders})",
                tuple(scoped_project_ids),
            ).fetchall()
        else:
            all_active = []

    never_engaged: List[Dict[str, Any]] = []
    heartbeat_stale: List[Dict[str, Any]] = []
    progress_stale: List[Dict[str, Any]] = []
    skipped_between_turns: List[Dict[str, Any]] = []
    now_iso = _now_iso()
    now = utc_now()
    options = dict(
        stale_threshold_minutes=stale_threshold_minutes,
        progress_threshold_minutes=progress_threshold_minutes,
        executor_ttl_overrides=executor_ttl_overrides,
    )
    deploy_drivers = None
    for row in reclaim_facts(conn, all_active):
        sid = row["session_id"]
        signals = read_activity_signals(conn, sid, session_facts=row)
        if not row["holds_work_claim"] and deploy_drivers is None:
            deploy_drivers = deployment_driver_holds(conn)
        row["holds_work_claim"] = row["holds_work_claim"] or sid in (deploy_drivers or {})
        row["last_heartbeat"] = signals.activity_at
        decision = automatic_reclaim(row, now=now, **options)
        evidence = decision.evidence
        entry = {
            "session_id": row["session_id"],
            "org_id": row.get("org_id"),
            "executor": evidence.executor,
            "effective_ttl_minutes": evidence.effective_ttl_minutes,
            "has_active_holdings": row["has_active_holdings"],
            "activity_at": signals.activity_at,
            "last_event_at": evidence.last_event_at,
            "stale_minutes": age_minutes_since(signals.activity_at),
            "reason": decision.reason,
        }
        if evidence.ended_at is not None:
            continue
        if not decision.is_reclaimable:
            if decision.reason in (REASON_ACTIVE_WORK_CLAIM, REASON_LIVE_QA_EXECUTION):
                skipped_between_turns.append(entry)
            elif activity_is_stale(
                evidence.activity_at,
                executor=evidence.executor,
                now=now,
                base_ttl_minutes=stale_threshold_minutes,
            ):
                if decision.reason in (
                    REASON_KEEPALIVE_HELD,
                    REASON_WAKE_DELIVERY_IN_FLIGHT,
                ):
                    skipped_between_turns.append(entry)
                    _emit_reclaim_aborted(
                        decision, now_iso, has_active_holdings=row["has_active_holdings"]
                    )
                else:
                    skipped_between_turns.append({**entry, "reason": "between_turns"})
            continue
        if not row.get("tool_call_count"):
            never_engaged.append({**entry, "reason": "never_engaged"})
        elif decision.reason == "progress_stale":
            progress_stale.append(entry)
        else:
            heartbeat_stale.append(entry)

    # Reclaim all identified sessions and emit one HarnessSessionStaleReclaimed per
    # session.  Each candidate is re-classified inside this loop via
    # the shared activity classifier; if fresh activity has landed since the
    # snapshot, the mutation is skipped and ReclaimAborted is emitted with
    # scope='session_cleanup' instead.
    total_reclaimed = org_scoped_reclaimed = 0
    reclaim_batches = never_engaged + heartbeat_stale + progress_stale
    for entry in reclaim_batches:
        sid = entry["session_id"]
        from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle

        lock_session_rows_for_claim_lifecycle(conn, (sid,))
        row = reclaim_facts(conn, [{"session_id": sid}])[0]
        row["holds_work_claim"] = session_has_active_work_claim(
            conn, sid
        ) or sid in deployment_driver_holds(conn)
        row["owns_live_qa_execution"] = session_owns_live_qa_execution(conn, sid)
        if row["holds_work_claim"] or row["owns_live_qa_execution"]:
            recheck = automatic_reclaim(row, **options)
        else:
            recheck = classify_reclaimable(
                conn,
                sid,
                scope=SCOPE_SESSION_CLEANUP,
                base_ttl_minutes=stale_threshold_minutes,
                overrides=executor_ttl_overrides,
                progress_threshold_minutes=progress_threshold_minutes,
            )
        if recheck.evidence.ended_at is not None or not recheck.is_reclaimable:
            skipped_between_turns.append(
                {**entry, "reason": recheck.reason, "recheck": True}
            )
            _emit_reclaim_aborted(
                recheck,
                now_iso,
                has_active_holdings=row["has_active_holdings"],
                candidate_reason=entry["reason"],
            )
            continue

        # Read before the reclaim clears it, so the event reports what it collected.
        chain_state = chain_pending_state(conn, sid)
        claim_count_row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM work_claims
               WHERE session_id = %s AND released_at IS NULL""",
            (sid,),
        ).fetchone()
        released_claim_count = int(claim_count_row["cnt"] or 0)

        try:
            reclaim_stale_session(conn, sid)
        except SessionError as exc:
            skipped_between_turns.append(
                {
                    **entry,
                    "reason": exc.code.lower(),
                    "recheck": True,
                    "recovery": exc.message,
                }
            )
            continue
        total_reclaimed += 1
        org_scoped_reclaimed += int(entry["org_id"] is not None)

        _sa._emit_event(
            EVENT_HARNESS_SESSION_STALE_RECLAIMED,
            event_kind="system",
            event_type="session_lifecycle",
            source_type="backend",
            session_id=sid,
            severity="INFO",
            outcome="completed",
            context={
                "reason": entry["reason"],
                "executor": entry["executor"],
                "stale_minutes": entry["stale_minutes"],
                "last_event_at": entry["last_event_at"],
                "effective_ttl_minutes": recheck.evidence.effective_ttl_minutes,
                "has_active_holdings": row["has_active_holdings"],
                "released_claim_count": released_claim_count,
                "chain_checkpoint_cleared": chain_state.chainable,
                "chain_checkpoint_step": chain_state.step,
                "janitor_now": now_iso,
            },
        )

    # The stale-session sweep is the bounded lifecycle janitor for scratch too.
    # The pruner requires positive ended-session or dead-PID proof and carries
    # its own machine-wide throttle, so validation DBs and concurrent sessions
    # cannot authorize deletion merely by omitting another session's row.
    if project_ids is None:
        try:
            scratch_cleanup = auto_prune_stale_scratch(conn).as_dict()
        except Exception as exc:  # noqa: BLE001 - report janitor boundary failures
            scratch_cleanup = ScratchPruneResult(
                failure_count=1,
                issues=[f"automatic scratch cleanup failed: {exc}"],
            ).as_dict()
    else:
        scratch_cleanup = ScratchPruneResult().as_dict()
        scratch_cleanup["scope_limited"] = True

    # Emit sweep-level event even when zero sessions reclaimed
    _sweep_duration_ms = int((_time.monotonic() - _sweep_start) * 1000)
    # Use a stable session_id for sweep-level events (not tied to any session)
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
        session_id="__sweep__",
        context={
            "project_ids": project_ids,
            "total_scanned": len(all_active),
            "total_reclaimed": total_reclaimed,
            "org_scoped_reclaimed": org_scoped_reclaimed,
            "sweep_duration_ms": _sweep_duration_ms,
            "never_engaged_count": len(never_engaged),
            "heartbeat_stale_count": len(heartbeat_stale),
            "progress_stale_count": len(progress_stale),
            "skipped_between_turns_count": len(skipped_between_turns),
            "scratch_cleanup": scratch_cleanup,
        },
    )

    return {
        "org_scoped_reclaimed": org_scoped_reclaimed,
        **sweep_receipt(
            never_engaged=never_engaged,
            heartbeat_stale=heartbeat_stale,
            progress_stale=progress_stale,
            skipped_between_turns=skipped_between_turns,
            total_reclaimed=total_reclaimed,
            scratch_cleanup=scratch_cleanup,
        ),
    }


def _emit_reclaim_aborted(
    decision: ReclaimClassification,
    now_iso: str,
    *,
    has_active_holdings: bool,
    candidate_reason: str | None = None,
) -> None:
    evidence = decision.evidence.as_payload()
    _sa._emit_session_event(
        EVENT_RECLAIM_ABORTED,
        session_id=decision.evidence.session_id,
        context={
            "scope": SCOPE_SESSION_CLEANUP,
            "original_session_id": decision.evidence.session_id,
            "attempting_session_id": None,
            "abort_reason": decision.reason,
            "candidate_reason": candidate_reason,
            "executor": evidence["executor"],
            "has_active_holdings": has_active_holdings,
            "effective_ttl_minutes": evidence["effective_ttl_minutes"],
            "original_session_last_heartbeat": evidence["last_heartbeat"],
            "original_session_last_event_at": evidence["last_event_at"],
            "janitor_now": now_iso,
        },
    )


cleanup_never_engaged_sessions = clean_stale_harness_sessions

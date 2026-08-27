"""Unified stale-session cleanup sweep."""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from . import db_backend
from .session_cleanup_holdings import active_holding_sessions, effective_cleanup_ttl
from .session_reclaim_activity import (
    SCOPE_SESSION_CLEANUP,
    classify_reclaimable,
    current_episode_progress_stamp,
    in_flight_activity_is_hard_stale,
    read_activity_signals,
)
from .session_reclaim_progress import parse_stamp
from .session_staleness import activity_is_stale
from .sessions_analytics_core import DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES
from .sessions_analytics import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_HARNESS_SESSION_STALE_RECLAIMED,
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    EVENT_RECLAIM_ABORTED,
    SessionError,
)
from .sessions_queries import _now_iso
from .sessions_render_end_chain_pending import chain_pending_state
from .sessions_render import reclaim_stale_session
from .scratch_auto_prune import ScratchPruneResult, auto_prune_stale_scratch
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns


def _minutes_since(iso_value: Optional[str]) -> int:
    ts = parse_stamp(iso_value)
    if ts is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds() // 60))


def clean_stale_harness_sessions(
    conn: Any,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    progress_threshold_minutes: int = DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    *,
    executor_ttl_overrides: Optional[Dict[str, int]] = None,
    project_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Unified stale-session cleanup.

    The short TTL applies to empty sessions. Sessions with an
    active work claim, session-owned strategy-document lock, or session-owned
    coordination lease use the longer holdings TTL.

    Each reclaim emits exactly one ``HarnessSessionStaleReclaimed`` event with
    ``stale_minutes``, ``last_event_at``, ``released_claim_count``, ``executor``,
    and ``reason`` so the ledger has a single canonical entry per cleanup
    event.  Per-claim ``WorkReclaimed`` events are still emitted by
    ``reclaim_stale_session`` for audit continuity.

    Returns::

        {
            "never_engaged": [...],
            "heartbeat_stale": [...],
            "progress_stale": [...],
            "skipped_between_turns": [...],
            "total_reclaimed": int,
        }
    """
    _sweep_start = _time.monotonic()

    active_cols = set(_schema_get_columns(conn, "harness_sessions"))
    executor_col = "executor" if "executor" in active_cols else None
    activity_cols = "last_tool_call_at" in active_cols
    select_cols = "session_id, offered_at"
    if executor_col:
        select_cols += ", executor"
    if activity_cols:
        select_cols += ", last_tool_call_at, tool_call_count"
    if "episode_started_at" in active_cols:
        select_cols += ", episode_started_at"

    if project_ids is None:
        all_active = conn.execute(
            f"SELECT {select_cols} FROM harness_sessions WHERE ended_at IS NULL",
        ).fetchall()
    else:
        scoped_project_ids = sorted({int(value) for value in project_ids})
        if scoped_project_ids:
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            placeholders = ", ".join(marker for _ in scoped_project_ids)
            all_active = conn.execute(
                f"SELECT {select_cols} FROM harness_sessions "
                "WHERE ended_at IS NULL "
                f"AND project_id IN ({placeholders})",
                tuple(scoped_project_ids),
            ).fetchall()
        else:
            all_active = []

    never_engaged: List[Dict[str, Any]] = []
    heartbeat_stale: List[Dict[str, Any]] = []
    progress_stale: List[Dict[str, Any]] = []
    skipped_between_turns: List[Dict[str, Any]] = []
    holding_sessions = active_holding_sessions(conn)

    now_iso = _now_iso()

    for sess_row in all_active:
        sid = sess_row["session_id"]
        executor = (
            sess_row["executor"] if executor_col and sess_row["executor"] else "unknown"
        )
        has_active_holdings = sid in holding_sessions
        effective_ttl = effective_cleanup_ttl(
            executor,
            base_ttl_minutes=stale_threshold_minutes,
            executor_ttl_overrides=executor_ttl_overrides,
            has_active_holdings=has_active_holdings,
            holdings_ttl_minutes=DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
        )
        effective_progress_ttl = (
            max(progress_threshold_minutes, effective_ttl)
            if has_active_holdings
            else progress_threshold_minutes
        )

        if activity_cols:
            tool_count = sess_row["tool_call_count"] or 0
            latest_event_at = sess_row["last_tool_call_at"]
        else:
            tool_count = 0
            latest_event_at = None
        episode_started_at = (
            sess_row["episode_started_at"]
            if "episode_started_at" in active_cols
            else None
        )

        evidence = read_activity_signals(
            conn, sid, base_ttl_minutes=effective_ttl, overrides={}
        )
        activity_at = evidence.activity_at
        if evidence.in_flight:
            is_stale = in_flight_activity_is_hard_stale(
                activity_at,
                effective_ttl_minutes=effective_ttl,
            )
        else:
            is_stale = activity_is_stale(
                activity_at,
                executor=None,
                base_ttl_minutes=effective_ttl,
                executor_ttl_overrides={},
            )
        stale_minutes = _minutes_since(activity_at) if activity_at else 0

        entry = {
            "session_id": sid,
            "executor": executor,
            "effective_ttl_minutes": effective_ttl,
            "has_active_holdings": has_active_holdings,
            "activity_at": activity_at,
            "last_event_at": latest_event_at,
            "stale_minutes": stale_minutes,
        }

        progress_stale_flag = False
        progress_at = current_episode_progress_stamp(
            latest_event_at,
            episode_started_at,
        )
        if tool_count > 0 and progress_at:
            progress_stale_flag = activity_is_stale(
                progress_at,
                executor=None,
                base_ttl_minutes=effective_progress_ttl,
                executor_ttl_overrides={},
            )

        if not is_stale:
            if progress_stale_flag:
                progress_stale.append({**entry, "reason": "progress_stale"})
                continue
            # Spared despite the base threshold — by the holdings-aware TTL
            # or by live in-flight evidence. A session still inside the base
            # threshold is simply fresh and needs no explanation.
            if activity_is_stale(
                activity_at,
                executor=None,
                base_ttl_minutes=stale_threshold_minutes,
                executor_ttl_overrides={},
            ):
                skipped_between_turns.append({**entry, "reason": "between_turns"})
            continue

        if tool_count == 0:
            never_engaged.append({**entry, "reason": "never_engaged"})
        elif progress_stale_flag:
            progress_stale.append({**entry, "reason": "progress_stale"})
        else:
            heartbeat_stale.append({**entry, "reason": "heartbeat_stale"})

    # Reclaim all identified sessions and emit one HarnessSessionStaleReclaimed per
    # session.  Each candidate is re-classified inside this loop via
    # the shared activity classifier; if fresh activity has landed since the
    # snapshot, the mutation is skipped and ReclaimAborted is emitted with
    # scope='session_cleanup' instead.
    total_reclaimed = 0
    reclaim_batches = never_engaged + heartbeat_stale + progress_stale
    for entry in reclaim_batches:
        sid = entry["session_id"]
        has_active_holdings = sid in active_holding_sessions(conn)
        effective_ttl = effective_cleanup_ttl(
            entry["executor"],
            base_ttl_minutes=stale_threshold_minutes,
            executor_ttl_overrides=executor_ttl_overrides,
            has_active_holdings=has_active_holdings,
            holdings_ttl_minutes=DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
        )

        recheck = classify_reclaimable(
            conn,
            sid,
            base_ttl_minutes=effective_ttl,
            overrides={},
            progress_threshold_minutes=(
                max(progress_threshold_minutes, effective_ttl)
                if has_active_holdings
                else progress_threshold_minutes
            ),
        )
        if not recheck.is_reclaimable:
            evidence_payload = recheck.evidence.as_payload()
            _sa._emit_session_event(
                EVENT_RECLAIM_ABORTED,
                session_id=sid,
                context={
                    "scope": SCOPE_SESSION_CLEANUP,
                    "original_session_id": sid,
                    "attempting_session_id": None,
                    "abort_reason": recheck.reason,
                    "candidate_reason": entry["reason"],
                    "executor": evidence_payload["executor"],
                    "has_active_holdings": has_active_holdings,
                    "effective_ttl_minutes": evidence_payload["effective_ttl_minutes"],
                    "original_session_last_heartbeat": evidence_payload[
                        "last_heartbeat"
                    ],
                    "original_session_last_event_at": evidence_payload["last_event_at"],
                    "janitor_now": now_iso,
                },
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
        except SessionError:
            # Concurrently reclaimed or already ended — still report attempt
            continue
        total_reclaimed += 1

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
                "has_active_holdings": has_active_holdings,
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
            "sweep_duration_ms": _sweep_duration_ms,
            "never_engaged_count": len(never_engaged),
            "heartbeat_stale_count": len(heartbeat_stale),
            "progress_stale_count": len(progress_stale),
            "skipped_between_turns_count": len(skipped_between_turns),
            "scratch_cleanup": scratch_cleanup,
        },
    )

    return {
        "never_engaged": never_engaged,
        "heartbeat_stale": heartbeat_stale,
        "progress_stale": progress_stale,
        "skipped_between_turns": skipped_between_turns,
        "total_reclaimed": total_reclaimed,
        "scratch_cleanup": scratch_cleanup,
    }


# Public alias retained by the sessions front door.
cleanup_never_engaged_sessions = clean_stale_harness_sessions

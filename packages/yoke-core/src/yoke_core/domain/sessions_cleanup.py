"""Unified stale-session cleanup sweep."""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import sessions_analytics as _sa
from .session_reclaim_activity import (
    SCOPE_SESSION_CLEANUP,
    classify_reclaimable,
    latest_activity,
)
from .session_staleness import activity_is_stale
from .sessions_analytics import (
    DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    DEFAULT_STALE_THRESHOLD_MINUTES,
    EVENT_HARNESS_SESSION_STALE_RECLAIMED,
    EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
    EVENT_RECLAIM_ABORTED,
    SessionError,
)
from .sessions_queries import _now_iso
from .sessions_render import _resolve_effective_ttl, reclaim_stale_session
from .scratch_auto_prune import ScratchPruneResult, auto_prune_stale_scratch
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_harness.hooks.identity import is_codex


def _minutes_since(iso_value: Optional[str]) -> int:
    if not iso_value:
        return 0
    try:
        ts = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return max(0, int(delta.total_seconds() // 60))

def clean_stale_harness_sessions(
    conn: Any,
    stale_threshold_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    progress_threshold_minutes: int = DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    *,
    executor_ttl_overrides: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Unified stale-session cleanup.

    For each active session, derive the most recent activity timestamp as
    ``MAX(last_heartbeat, harness_sessions.last_tool_call_at)`` rather
    than just ``last_heartbeat``.  A session is considered stale when that
    combined activity timestamp is older than the effective TTL.

    **Executor-aware policy:** Codex has no true SessionEnd hook, so
    between-turn idle is normal.  Codex sessions use a longer TTL from
    ``EXECUTOR_STALE_TTL_OVERRIDES_MINUTES`` (or the caller-supplied override
    table).  Claude Code still benefits from the fast default TTL because its
    ``SessionEnd`` hook cleans up immediately on window close.

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
    # ``last_heartbeat`` is no longer in the SELECT — liveness derivation
    # routes through :func:`latest_activity` per session below. The
    # tool-activity signals are the harness_sessions columns the observe
    # pipeline stamps (last_tool_call_at / tool_call_count); minimal
    # fixtures without them read as never-engaged, matching the legacy
    # empty-ledger behavior.
    select_cols = "session_id, offered_at"
    if executor_col:
        select_cols += ", executor"
    if activity_cols:
        select_cols += ", last_tool_call_at, tool_call_count"

    all_active = conn.execute(
        f"SELECT {select_cols} FROM harness_sessions WHERE ended_at IS NULL",
    ).fetchall()

    never_engaged: List[Dict[str, Any]] = []
    heartbeat_stale: List[Dict[str, Any]] = []
    progress_stale: List[Dict[str, Any]] = []
    skipped_between_turns: List[Dict[str, Any]] = []

    # Informational "when this sweep ran" timestamp recorded on emitted
    # lifecycle events below.  No SQL-side comparison depends on this value,
    # so we use the canonical app-level formatter rather than paying for a
    # SQL round-trip and inheriting SQLite's naive-UTC representation.
    now_iso = _now_iso()

    for sess_row in all_active:
        sid = sess_row["session_id"]
        executor = (
            sess_row["executor"] if executor_col and sess_row["executor"] else "unknown"
        )
        effective_ttl = _resolve_effective_ttl(
            executor, stale_threshold_minutes, executor_ttl_overrides,
        )

        # Activity timestamp uses the latest tool call, not registration-
        # time signals — session-lifecycle writes happen during
        # registration itself and would make every just-begun session look
        # fresh, defeating the stale check. last_tool_call_at /
        # tool_call_count are stamped by the observe pipeline on
        # HarnessToolCallCompleted/Failed; ``latest_activity`` is the
        # canonical combined derivation, while the per-row columns drive
        # the never_engaged / progress_stale branch classifications.
        if activity_cols:
            tool_count = sess_row["tool_call_count"] or 0
            latest_event_at = sess_row["last_tool_call_at"]
        else:
            tool_count = 0
            latest_event_at = None

        activity_at = latest_activity(conn, sid, executor=executor)
        is_stale = activity_is_stale(
            activity_at,
            executor=executor,
            base_ttl_minutes=stale_threshold_minutes,
            executor_ttl_overrides=executor_ttl_overrides,
        ) if activity_at is not None else True
        stale_minutes = _minutes_since(activity_at) if activity_at else 0

        entry = {
            "session_id": sid,
            "executor": executor,
            "effective_ttl_minutes": effective_ttl,
            "activity_at": activity_at,
            "last_event_at": latest_event_at,
            "stale_minutes": stale_minutes,
        }

        # The combined-activity check is the "don't false-positive a
        # session that is still emitting events" guard.  When that passes, we
        # still run the progress-stale check against the latest tool event so
        # sessions that heartbeat fine but stop making progress are still
        # reclaimed.
        progress_stale_flag = False
        if tool_count > 0 and latest_event_at:
            try:
                latest_event_dt = datetime.fromisoformat(
                    str(latest_event_at).replace("Z", "+00:00")
                )
                if latest_event_dt.tzinfo is None:
                    latest_event_dt = latest_event_dt.replace(tzinfo=timezone.utc)
                progress_stale_flag = latest_event_dt < (
                    datetime.now(timezone.utc)
                    - timedelta(minutes=progress_threshold_minutes)
                )
            except (TypeError, ValueError):
                progress_stale_flag = False

        if not is_stale:
            # Combined activity is fresh.  Still reclaim when the progress
            # signal says the session is wedged.
            if progress_stale_flag:
                progress_stale.append({**entry, "reason": "progress_stale"})
                continue
            # Fresh activity — skip.  For Codex sessions, record this
            # explicitly so the janitor can show the operator why we did not
            # reclaim a silent-but-recent session.
            if is_codex(executor):
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

        # Final recheck inside the same transaction window —
        # any heartbeat or tool-call event that landed since the snapshot
        # disqualifies the holder and aborts the mutation.
        recheck = classify_reclaimable(
            conn,
            sid,
            base_ttl_minutes=stale_threshold_minutes,
            overrides=executor_ttl_overrides,
            progress_threshold_minutes=progress_threshold_minutes,
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
                    "effective_ttl_minutes": evidence_payload[
                        "effective_ttl_minutes"
                    ],
                    "original_session_last_heartbeat": evidence_payload[
                        "last_heartbeat"
                    ],
                    "original_session_last_event_at": evidence_payload[
                        "last_event_at"
                    ],
                    "janitor_now": now_iso,
                },
            )
            continue

        # Count active claims before release so the reclaim event can report
        # released_claim_count accurately.
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
                "effective_ttl_minutes": entry["effective_ttl_minutes"],
                "released_claim_count": released_claim_count,
                "janitor_now": now_iso,
            },
        )

    # The stale-session sweep is the bounded lifecycle janitor for scratch too.
    # The pruner requires positive ended-session or dead-PID proof and carries
    # its own machine-wide throttle, so validation DBs and concurrent sessions
    # cannot authorize deletion merely by omitting another session's row.
    try:
        scratch_cleanup = auto_prune_stale_scratch(conn)
    except Exception as exc:  # noqa: BLE001 - report janitor boundary failures
        scratch_cleanup = ScratchPruneResult(
            failure_count=1,
            issues=[f"automatic scratch cleanup failed: {exc}"],
        )

    # Emit sweep-level event even when zero sessions reclaimed
    _sweep_duration_ms = int((_time.monotonic() - _sweep_start) * 1000)
    # Use a stable session_id for sweep-level events (not tied to any session)
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED,
        session_id="__sweep__",
        context={
            "total_scanned": len(all_active),
            "total_reclaimed": total_reclaimed,
            "sweep_duration_ms": _sweep_duration_ms,
            "never_engaged_count": len(never_engaged),
            "heartbeat_stale_count": len(heartbeat_stale),
            "progress_stale_count": len(progress_stale),
            "skipped_between_turns_count": len(skipped_between_turns),
            "scratch_cleanup": scratch_cleanup.as_dict(),
        },
    )

    return {
        "never_engaged": never_engaged,
        "heartbeat_stale": heartbeat_stale,
        "progress_stale": progress_stale,
        "skipped_between_turns": skipped_between_turns,
        "total_reclaimed": total_reclaimed,
        "scratch_cleanup": scratch_cleanup.as_dict(),
    }


# Public alias retained by the sessions front door.
cleanup_never_engaged_sessions = clean_stale_harness_sessions

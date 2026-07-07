"""HC-session-cwd-binding: surface live session-cwd binding mismatches.

Diagnostic surface paired with the lint at
:mod:`yoke_core.domain.lint_session_cwd`. For each active session
that holds one or more ``work_claims``, this HC asks: is the session's
most recently observed harness cwd inside a claimed worktree, under
the control plane of one of its claimed projects, or under a free
path? If not, the session is structurally misbound and the operator
should relaunch before a write lands.

The lint blocks individual tool calls structurally; this HC reveals
malformed sessions wholesale so the operator can spot them before any
single tool call trips the lint. Sessions with no claims pass
unconditionally — the orchestrator/control-plane session shape needs no
enforcement.

Read-only: never mutates state. Misses caused by transient telemetry
gaps degrade to "unknown" notes — false-FAILs are worse than false
allows for a diagnostic surface.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.lifecycle_progression import PRE_IMPLEMENTATION_STATUSES
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.lint_session_cwd_emit import emit_health_check_failed
from yoke_core.domain.lint_session_cwd_validate import validate_targets

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-session-cwd-binding"
_HC_DESC = (
    "Active sessions with work claims must run from a claimed worktree, "
    "control plane, or free path"
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rollback_quietly(conn) -> None:
    """Clear the aborted-transaction state a swallowed statement leaves on
    Postgres so subsequent probes on the same connection still run."""
    try:
        conn.rollback()
    except Exception:
        pass


def _latest_observed_cwd(conn, session_id: str) -> Optional[str]:
    """Return the cwd from the session's most recent PreToolUse envelope."""
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT envelope FROM events "
        f"WHERE session_id = {p} AND event_name = 'HarnessToolCallStarted' "
        "ORDER BY id DESC LIMIT 5",
        (session_id,),
    )
    for row in rows:
        envelope_raw = row["envelope"] if isinstance(row, dict) else row[0]
        if not envelope_raw:
            continue
        try:
            envelope = json.loads(envelope_raw)
        except Exception:
            continue
        cwd = envelope.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            return cwd.strip()
    return None


def hc_session_cwd_binding(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Flag active sessions whose observed cwd is not in their claim authority."""
    if not _base._table_exists(conn, "harness_sessions"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "harness_sessions table missing — nothing to check",
        )
        return
    if not _base._table_exists(conn, "work_claims"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "work_claims table missing — nothing to check",
        )
        return

    rows = query_rows(
        conn,
        "SELECT DISTINCT session_id FROM work_claims "
        "WHERE released_at IS NULL "
        "ORDER BY session_id",
    )
    if not rows:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "no active sessions with work claims",
        )
        return

    mismatches: List[str] = []
    unknown: List[str] = []
    matched_count = 0

    for row in rows:
        session_id = row["session_id"] if isinstance(row, dict) else row[0]
        if not session_id:
            continue
        observed_cwd = _latest_observed_cwd(conn, session_id)
        if observed_cwd is None:
            unknown.append(f"{session_id} (no recent cwd telemetry)")
            continue
        outcome = validate_targets(
            conn,
            session_id=session_id,
            targets=(),
            fallback_cwd=observed_cwd,
        )
        if outcome.allow:
            matched_count += 1
            continue
        claim_summary = ", ".join(
            f"YOK-{c.item_id}" + (f"/T{c.task_num}" if c.task_num else "")
            for c in outcome.claims
        ) or "(none)"
        mismatches.append(
            f"  - session {session_id}\n"
            f"    claims:   {claim_summary}\n"
            f"    observed: {observed_cwd}\n"
            f"    offender: {outcome.offending_target}"
        )
        emit_health_check_failed(
            session_id=session_id,
            offending_target=outcome.offending_target,
            claim_count=len(outcome.claims),
        )

    note_parts: List[str] = []
    if matched_count:
        note_parts.append(f"{matched_count} matched")
    if unknown:
        note_parts.append(f"{len(unknown)} unknown")
    if mismatches:
        note_parts.append(f"{len(mismatches)} mismatched")
    note_summary = ", ".join(note_parts) or "no claim-holding sessions"

    if mismatches:
        details = (
            f"{note_summary}\n\nMismatched sessions:\n"
            + "\n".join(mismatches)
        )
        if unknown:
            details += "\n\nUnknown (no cwd telemetry):\n  - " + "\n  - ".join(
                unknown
            )
        rec.record(_HC_NAME, _HC_DESC, "FAIL", details)
        return

    if unknown:
        details = (
            note_summary
            + "\n\nUnknown (no cwd telemetry):\n  - "
            + "\n  - ".join(unknown)
        )
        rec.record(_HC_NAME, _HC_DESC, "PASS", details)
        return

    rec.record(_HC_NAME, _HC_DESC, "PASS", note_summary)


_PRE_IMPL_HC_NAME = "HC-session-pre-implementing-activity"
_PRE_IMPL_HC_DESC = (
    "Sessions with active claims must flip status to implementing "
    "before logging sustained tool-call activity"
)
# Activity thresholds: 30 minutes plus more than
# 10 ``HarnessToolCallCompleted`` events since claim acquisition is the
# canonical shape the gate catches.
_PRE_IMPL_MIN_AGE_SECONDS = 30 * 60
_PRE_IMPL_MIN_TOOL_CALLS = 10


def _pre_implementing_status_list() -> tuple[str, ...]:
    return tuple(sorted(PRE_IMPLEMENTATION_STATUSES))


def hc_session_pre_implementing_activity(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Flag stuck pre-implementing sessions.

    For each non-terminal ``work_claims`` row whose item is in a
    pre-implementing status, count ``HarnessToolCallCompleted`` events
    emitted by the holding session since the claim was acquired. Flag
    sessions whose claim age exceeds 30 minutes AND that emitted more
    than 10 tool-call events in that window. Skips cleanly when the
    schema is minimal (test fixtures without ``items.status`` or
    ``work_claims.claimed_at``).
    """
    if not _base._table_exists(conn, "work_claims"):
        rec.record(_PRE_IMPL_HC_NAME, _PRE_IMPL_HC_DESC, "PASS",
                   "work_claims table missing — nothing to check")
        return
    if not _base._table_exists(conn, "items"):
        rec.record(_PRE_IMPL_HC_NAME, _PRE_IMPL_HC_DESC, "PASS",
                   "items table missing — nothing to check")
        return

    statuses = _pre_implementing_status_list()
    p = _p(conn)
    placeholders = ",".join([p] * len(statuses))
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=int(_PRE_IMPL_MIN_AGE_SECONDS))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = (*statuses, cutoff)
    try:
        rows = query_rows(
            conn,
            "SELECT wc.session_id, wc.item_id, wc.claimed_at, i.status "
            "FROM work_claims wc JOIN items i ON i.id = wc.item_id "
            "WHERE wc.released_at IS NULL "
            f"AND i.status IN ({placeholders}) "
            "AND wc.claimed_at IS NOT NULL "
            f"AND wc.claimed_at <= {p} "
            "ORDER BY wc.claimed_at",
            params,
        )
    except db_backend.operational_error_types(conn):
        _rollback_quietly(conn)
        rec.record(_PRE_IMPL_HC_NAME, _PRE_IMPL_HC_DESC, "PASS",
                   "schema missing required columns — nothing to check")
        return

    flagged: List[str] = []
    for row in rows:
        session_id = row["session_id"] if isinstance(row, dict) else row[0]
        item_id = row["item_id"] if isinstance(row, dict) else row[1]
        claimed_at = row["claimed_at"] if isinstance(row, dict) else row[2]
        status = row["status"] if isinstance(row, dict) else row[3]
        if not session_id or not claimed_at:
            continue
        try:
            tool_count_rows = query_rows(
                conn,
                "SELECT COUNT(*) AS c FROM events "
                f"WHERE session_id = {p} AND event_name = "
                "'HarnessToolCallCompleted' "
                f"AND created_at >= {p}",
                (session_id, claimed_at),
            )
        except db_backend.operational_error_types(conn):
            _rollback_quietly(conn)
            continue
        if not tool_count_rows:
            continue
        count_val = (
            tool_count_rows[0]["c"]
            if isinstance(tool_count_rows[0], dict)
            else tool_count_rows[0][0]
        )
        if not isinstance(count_val, int) or count_val <= _PRE_IMPL_MIN_TOOL_CALLS:
            continue
        flagged.append(
            f"  - session {session_id}\n"
            f"    item:        YOK-{item_id}\n"
            f"    status:      {status}\n"
            f"    claimed_at:  {claimed_at}\n"
            f"    tool_calls:  {count_val}"
        )

    if flagged:
        details = (
            f"{len(flagged)} stuck pre-implementing session(s) — re-run "
            "/yoke advance ... implementation to finish finalize:\n\n"
            + "\n".join(flagged)
        )
        rec.record(_PRE_IMPL_HC_NAME, _PRE_IMPL_HC_DESC, "FAIL", details)
        return
    rec.record(_PRE_IMPL_HC_NAME, _PRE_IMPL_HC_DESC, "PASS",
               "no stuck pre-implementing sessions detected")


__all__ = [
    "hc_session_cwd_binding",
    "hc_session_pre_implementing_activity",
]

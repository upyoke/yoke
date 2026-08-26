"""HC-stop-hook-chain-end-deferred: stranded Stop deferrals, plus chain membership.

A deferred Stop that aged past the stale window is only a warning when
nothing resolved it: later completed tool use, a cap-reached record, a
terminal/blocked status change, or ``HarnessSessionEnded``. The Stop chain
must also keep steering report routing and the promised-work gate ahead of
lifecycle dispatch.
"""

from __future__ import annotations

from typing import List

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-stop-hook-chain-end-deferred"
_HC_DESC = "Stop-hook deferred chains that aged past the heartbeat-stale window"
_MEMBER_NAME = "HC-stop-hook-chain-membership"
_MEMBER_DESC = "Stop chain registers report routing and the work gate before dispatch"
_EXPECTED_STOP = [
    "yoke_core.domain.turn_end_steering_report",
    "yoke_core.domain.turn_end_promised_work_gate",
    "yoke_core.hooks.session_message_delivery",
    "yoke_core.hooks.session_launch_attestation",
    "yoke_core.hooks.session_dispatch",
]

_LOOKBACK_HOURS = 24
_STALE_WINDOW_MIN = 60


def _record_membership(rec: RecordCollector) -> None:
    chain = ordered_pipeline_for("Stop")
    if chain == _EXPECTED_STOP:
        rec.record(_MEMBER_NAME, _MEMBER_DESC, "PASS", "")
        return
    rec.record(
        _MEMBER_NAME,
        _MEMBER_DESC,
        "FAIL",
        f"Stop chain is {chain}; expected {_EXPECTED_STOP}",
    )


def _resolution_sql(conn) -> str:
    clauses = [
        """
          AND NOT EXISTS (
            SELECT 1 FROM events e2
            WHERE e2.session_id = e.session_id
              AND e2.event_name = 'HarnessSessionEnded'
              AND (e2.created_at)::timestamp >= (e.created_at)::timestamp
          )
        """,
    ]
    if _column_exists(conn, "events", "envelope"):
        clauses.append(
            """
          AND COALESCE((e.envelope)::jsonb #>> '{context,cap_reached}', '')
              <> 'true'
          AND COALESCE((e.envelope)::jsonb #>> '{context,reason}', '')
              <> 'reinjection_cap_reached'
          AND NOT EXISTS (
            SELECT 1 FROM events e3
            WHERE e3.session_id = e.session_id
              AND (e3.created_at)::timestamp >= (e.created_at)::timestamp
              AND (
                COALESCE((e3.envelope)::jsonb #>> '{context,cap_reached}', '')
                    = 'true'
                OR COALESCE((e3.envelope)::jsonb #>> '{context,reason}', '')
                    = 'reinjection_cap_reached'
                OR (
                    e3.event_name = 'ItemStatusChanged'
                    AND COALESCE(
                        (e3.envelope)::jsonb #>> '{context,to_status}', ''
                    ) IN ('done', 'blocked')
                )
              )
          )
            """
        )
    if _column_exists(conn, "events", "hook_event_name"):
        clauses.append(
            """
          AND NOT EXISTS (
            SELECT 1 FROM events e4
            WHERE e4.session_id = e.session_id
              AND (e4.created_at)::timestamp > (e.created_at)::timestamp
              AND e4.hook_event_name IN ('PreToolUse', 'PostToolUse')
          )
            """
        )
    return "".join(clauses)


def hc_stop_hook_chain_end_deferred(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    _record_membership(rec)
    if not _base._table_exists(conn, "events"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "events table missing — skipping")
        return

    rows = query_rows(
        conn,
        f"""
        SELECT e.id, e.session_id, e.item_id, e.created_at
        FROM events e
        WHERE e.event_name = 'ChainEndDeferred'
          AND (e.created_at)::timestamp >= ({now_sql(offset_hours=-_LOOKBACK_HOURS)})::timestamp
          AND (e.created_at)::timestamp <= ({now_sql(offset_minutes=-_STALE_WINDOW_MIN)})::timestamp
          {_resolution_sql(conn)}
        ORDER BY e.created_at ASC
        """,
    )

    if not rows:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(rows)} ChainEndDeferred event(s) in the last {_LOOKBACK_HOURS}h "
        f"aged past the {_STALE_WINDOW_MIN}-minute stale window without a "
        "resolving follow-up (tool use, cap-reached, terminal transition, or "
        "HarnessSessionEnded). Investigate whether the chain was abandoned."
    ]
    for row in rows[:10]:
        sid = row["session_id"] or "(none)"
        item = row["item_id"] or "(none)"
        issues.append(f"  - session={sid} item={item} created_at={row['created_at']}")
    if len(rows) > 10:
        issues.append(f"  ... and {len(rows) - 10} more")
    issues.append(
        "- Inspect via: `python3 -m yoke_core.cli.db_router events list "
        "--event-name ChainEndDeferred`"
    )

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))

"""HC-stop-hook-chain-end-deferred: detect chains the structural fix protected but the agent never returned to.

The Stop hook fires after every turn boundary. When ``end_session_if_empty``
declines to end a session because a chainable checkpoint still has budget
remaining, it emits ``ChainEndDeferred`` and leaves the session alive for
the next agent turn to resume. The 60-minute heartbeat-stale window is the
safety net for the legitimate "the agent crashed and abandoned the chain"
case — a session that never returns gets reclaimed by the next session-offer.

This HC is the operator-facing observability surface for the case in
between: a deferred chain that aged past the stale window without a
follow-up ``HarnessSessionEnded`` row. That is a signal — operator-skill
prose drift, agent muscle memory drift, or a real chain abandonment —
the operator should investigate.

Surface: WARN with the affected sessions and the first deferred event's
context. The HC does not auto-end the sessions; the standard reclaim path
already handles them.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-stop-hook-chain-end-deferred"
_HC_DESC = "Stop-hook deferred chains that aged past the heartbeat-stale window"

_LOOKBACK_HOURS = 24
_STALE_WINDOW_MIN = 60


def hc_stop_hook_chain_end_deferred(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
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
          AND NOT EXISTS (
            SELECT 1 FROM events e2
            WHERE e2.session_id = e.session_id
              AND e2.event_name = 'HarnessSessionEnded'
              AND (e2.created_at)::timestamp >= (e.created_at)::timestamp
          )
        ORDER BY e.created_at ASC
        """,
    )

    if not rows:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(rows)} ChainEndDeferred event(s) in the last {_LOOKBACK_HOURS}h "
        f"aged past the {_STALE_WINDOW_MIN}-minute stale window without a "
        "follow-up HarnessSessionEnded. Investigate whether the chain was "
        "abandoned (operator killed the harness, session crashed) or whether "
        "operator-skill prose / agent muscle memory drifted — the next "
        "session-offer's reclaim path will recover the claim itself."
    ]
    for row in rows[:10]:
        sid = row["session_id"] or "(none)"
        item = row["item_id"] or "(none)"
        issues.append(
            f"  - session={sid} item={item} created_at={row['created_at']}"
        )
    if len(rows) > 10:
        issues.append(f"  ... and {len(rows) - 10} more")
    issues.append(
        "- Inspect via: `python3 -m yoke_core.cli.db_router events list "
        "--event-name ChainEndDeferred`"
    )

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))

"""Who is holding an item work claim in one project, right now.

Split from the report itself because "which live sessions hold item claims"
is a question with one answer regardless of what any report does with it:
the report decides which holders are quiet, stuck, or in flight, and this
module decides only who the holders are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.sessions_holdings_claim_facts import clear_failed_read
from yoke_core.domain.steering_fleet_report_detectors import age_seconds
from yoke_core.domain.turn_end_unfinished_work import waiting_on_landing
from yoke_core.domain.work_claim_targets import scope_int_sql


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class ClaimHolder:
    """One live session holding one item's work claim."""

    session_id: str
    item_id: int
    public_ref: str
    mode: str
    parked: bool
    last_activity_at: str
    idle_seconds: int
    quiet_reason: str = ""
    native_process_gone_at: str = ""
    hand_started: bool = False

    @property
    def native_process_gone(self) -> bool:
        return bool(self.native_process_gone_at)


def _held_item_rows(conn: Any, *, project_id: int) -> list[dict[str, Any]]:
    """Every unreleased item work claim in one project, with its live session.

    One read, and only the facts a holder row shows. The complete holdings
    projection answers a different question — everything every session has
    ever held, across every project, with path, strategy and coordination
    observations built alongside — and a report that keeps the current item
    holders of one project paid for all of it.
    """
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    marker = _p(conn)
    try:
        rows = conn.execute(
            f"SELECT {item_id} AS item_id, wc.session_id AS session_id, "
            "wc.claimed_at AS claimed_at, "
            "i.project_sequence AS project_sequence, i.merged_at AS merged_at, "
            "i.merge_queue_enqueued_at AS merge_queue_enqueued_at, "
            "i.merge_queue_landed_at AS merge_queue_landed_at, "
            "p.public_item_prefix AS prefix, "
            "hs.mode AS mode, hs.quiet_reason AS quiet_reason, "
            "hs.last_tool_call_at AS last_tool_call_at, "
            "hs.last_heartbeat AS last_heartbeat, "
            "hs.episode_started_at AS episode_started_at, "
            "hs.turn_posture AS turn_posture, "
            "hs.turn_posture_at AS turn_posture_at, "
            "hs.native_process_gone_at AS native_process_gone_at, "
            "hs.native_process_gone_evidence AS native_process_gone_evidence, "
            "EXISTS(SELECT 1 FROM session_launches l "
            "WHERE l.registered_session_id = hs.session_id) AS launch_recorded "
            "FROM work_claims wc "
            f"JOIN items i ON i.id = {item_id} "
            "JOIN projects p ON p.id = i.project_id "
            "JOIN harness_sessions hs ON hs.session_id = wc.session_id "
            "WHERE wc.released_at IS NULL AND wc.target_kind = 'item' "
            f"AND i.project_id = {marker} "
            "AND hs.ended_at IS NULL AND hs.terminated_at IS NULL "
            f"ORDER BY wc.claimed_at, {item_id}",
            (int(project_id),),
        ).fetchall()
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return []
    return [dict(row) for row in rows]


def claim_holders(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[ClaimHolder, ...]:
    """Live sessions holding an item work claim in one project.

    Ended and terminated sessions are excluded: their claims are the
    stale-session sweep's business, and reporting a session that is already
    gone as an idle worker re-fires the same false alarm on every pass.
    """
    holders = []
    for row in _held_item_rows(conn, project_id=project_id):
        last_activity = str(row.get("last_tool_call_at") or row.get("claimed_at") or "")
        mode = str(row.get("mode") or "")
        process = (
            current_native_process_observation(
                row,
                landing_wait=waiting_on_landing(row),
            )
            or {}
        )
        holders.append(
            ClaimHolder(
                session_id=str(row["session_id"]),
                item_id=int(row["item_id"]),
                public_ref=format_item_ref(
                    None, row["prefix"], row["project_sequence"]
                ),
                mode=mode,
                parked=session_is_parked(mode),
                last_activity_at=last_activity,
                idle_seconds=age_seconds(last_activity, now) or 0,
                quiet_reason=str(row.get("quiet_reason") or ""),
                native_process_gone_at=str(process.get("observed_at") or ""),
                hand_started=not bool(row.get("launch_recorded")),
            )
        )
    return tuple(holders)


__all__ = ["ClaimHolder", "claim_holders"]

"""Who is holding an item work claim in one project, right now.

Split from the report itself because "which live sessions hold item claims"
is a question with one answer regardless of what any report does with it:
the report decides which holders are quiet, stuck, or in flight, and this
module decides only who the holders are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.session_holdings import work_holding_key
from yoke_core.domain import db_backend
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session
from yoke_core.domain.steering_fleet_report_detectors import age_seconds


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
    native_process_gone_at: str = ""

    @property
    def native_process_gone(self) -> bool:
        return bool(self.native_process_gone_at)


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
    holdings = session_holdings_by_session(conn, previous_limit=0)
    item_prefix = work_holding_key("item", item_id="")
    candidates = []
    for session_id, grouped in holdings.items():
        for entry in grouped.get("current") or []:
            target_key = str(entry.get("target_key") or "")
            if (
                entry.get("holding_kind") != "work_claim"
                or entry.get("target_kind") != "item"
                or int(entry.get("item_project_id") or 0) != int(project_id)
                or not target_key.startswith(item_prefix)
            ):
                continue
            item_id = target_key.removeprefix(item_prefix)
            if item_id.isdigit():
                candidates.append((session_id, int(item_id), entry))
    if not candidates:
        return ()
    marker = _p(conn)
    session_ids = sorted({session_id for session_id, _item_id, _entry in candidates})
    placeholders = ",".join(marker for _ in session_ids)
    rows = conn.execute(
        "SELECT session_id,mode,last_tool_call_at,last_heartbeat,episode_started_at,"
        "native_process_gone_at,native_process_gone_evidence "
        "FROM harness_sessions "
        f"WHERE session_id IN ({placeholders}) AND ended_at IS NULL "
        "AND terminated_at IS NULL",
        tuple(session_ids),
    ).fetchall()
    sessions = {str(row["session_id"]): dict(row) for row in rows}
    holders = []
    for session_id, item_id, entry in sorted(
        candidates, key=lambda value: (str(value[2].get("claimed_at") or ""), value[1])
    ):
        record = sessions.get(session_id)
        if record is None:
            continue
        last_activity = str(
            record.get("last_tool_call_at") or entry.get("claimed_at") or ""
        )
        mode = str(record.get("mode") or "")
        process = current_native_process_observation(record) or {}
        holders.append(
            ClaimHolder(
                session_id=session_id,
                item_id=item_id,
                public_ref=str(
                    entry.get("public_ref") or entry.get("target") or item_id
                ),
                mode=mode,
                parked=session_is_parked(mode),
                last_activity_at=last_activity,
                idle_seconds=age_seconds(last_activity, now) or 0,
                native_process_gone_at=str(process.get("observed_at") or ""),
            )
        )
    return tuple(holders)



__all__ = ["ClaimHolder", "claim_holders"]

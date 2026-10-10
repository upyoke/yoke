"""Who is holding an item work claim in one project, right now.

Split from the report itself because "which live sessions hold item claims"
is a question with one answer regardless of what any report does with it:
the report decides which holders are quiet, stuck, or in flight, and this
module decides only who the holders are.
"""

from __future__ import annotations

from yoke_contracts.timestamps import format_instant

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_tool_call_projections import (
    OPEN_TOOL_CALL_COLUMN,
    open_tool_call_expression,
)
from yoke_core.domain.steering_fleet_report_detectors import parse_stamp
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_resume_in_flight import (
    resumable_from_transcript,
    resumes_in_flight,
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
    last_activity_at: datetime | None
    idle_seconds: int
    quiet_reason: str = ""
    native_process_gone_at: datetime | None = None
    hand_started: bool = False
    #: Why this machine's containment sweep ended the native, when it did.
    #: A holder whose process a sweep stopped is not a worker that went
    #: quiet: something on its own machine decided it had no authority, and
    #: the two want opposite responses from a seat.
    contained_reason: str = ""
    #: A turn stopped after starting a call whose completion never arrived.
    call_interrupted: bool = False
    #: When a wake that answered the recorded exit started. A resuming
    #: holder is not a dead one, so it carries no process-gone stamp.
    resume_started_at: datetime | None = None
    #: The holder's own surface resumes a stopped native from its transcript
    #: when messaged (its declared ``message_stopped`` operation).
    resumable_from_transcript: bool = False

    @property
    def requires_immediate_alarm(self) -> bool:
        return self.native_process_gone or (self.call_interrupted and not self.parked)

    @property
    def native_process_gone(self) -> bool:
        return bool(self.native_process_gone_at)

    @property
    def contained_by_sweep(self) -> bool:
        return bool(self.contained_reason)

    @property
    def resuming(self) -> bool:
        return bool(self.resume_started_at)

    def process_phrase(self) -> str:
        """What the holder's process is doing and what a seat does about it.

        Empty for a live process; the caller decides whether quiet makes
        that worth a line. None of these states is evidence for terminating
        a worker that a message would bring back.
        """
        if self.resuming:
            return (
                f"resuming now (wake started {format_instant(self.resume_started_at)}, after "
                "its recorded exit) — not dead; let it start"
            )
        if self.contained_by_sweep:
            # Not a worker that went quiet: its own machine ended it.
            return f"contained by sweep: {self.contained_reason}, claims held"
        if not self.native_process_gone:
            return ""
        if self.resumable_from_transcript:
            return (
                "idle, process exited — message it to resume from transcript "
                f"`yoke say --item {self.public_ref} --stdin`"
            )
        return (
            "process gone, claims held — this surface cannot resume by "
            "message; terminate deliberately if dead"
        )


def _contained_reason(process: dict[str, Any]) -> str:
    """The sweep's own reason for ending this native, when it recorded one.

    Containment writes the reason onto the death it caused, so a holder whose
    process a sweep stopped can be told from one whose native merely exited.
    Anything else -- an ordinary exit, a crash, a death nobody explained --
    leaves this empty rather than inventing a cause.
    """
    evidence = process.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    reason = evidence.get("containment_reason")
    return reason.strip() if isinstance(reason, str) else ""


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
    open_call = open_tool_call_expression(session_alias="hs")
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
            "hs.executor_surface AS executor_surface, "
            "hs.executor_version AS executor_version, "
            "EXISTS(SELECT 1 FROM session_launches l "
            "WHERE l.registered_session_id = hs.session_id) AS launch_recorded "
            f"{open_call} "
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
    rows = _held_item_rows(conn, project_id=project_id)
    processes = {
        str(row["session_id"]): current_native_process_observation(
            row, landing_wait=waiting_on_landing(row)
        )
        or {}
        for row in rows
    }
    # Only a recorded exit can be answered by a resume, so a fleet with no
    # exit on record pays nothing beyond its one holder read.
    resumes = resumes_in_flight(
        conn,
        (session_id for session_id, process in processes.items() if process),
        now=parse_stamp(now),
    )
    for row in rows:
        last_activity = parse_stamp(
            row.get("last_tool_call_at")
            if row.get("last_tool_call_at") is not None
            else row.get("claimed_at")
        )
        mode = str(row.get("mode") or "")
        process = processes[str(row["session_id"])]
        resume = resumes.get(str(row["session_id"]))
        if resume is not None:
            process = {}
        call_start = parse_stamp(row.get(OPEN_TOOL_CALL_COLUMN))
        stopped_at = parse_stamp(row.get("turn_posture_at"))
        interrupted = (
            row.get("turn_posture") == "waiting"
            and call_start is not None
            and stopped_at is not None
            and stopped_at >= call_start
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
                native_process_gone_at=parse_stamp(process.get("observed_at")),
                contained_reason=_contained_reason(process),
                hand_started=not bool(row.get("launch_recorded")),
                call_interrupted=interrupted,
                resume_started_at=parse_stamp(resume.started_at) if resume else None,
                resumable_from_transcript=resumable_from_transcript(
                    row.get("executor_surface"), row.get("executor_version")
                ),
            )
        )
    return tuple(holders)


__all__ = ["ClaimHolder", "claim_holders"]

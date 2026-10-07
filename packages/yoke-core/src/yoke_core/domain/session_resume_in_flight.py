"""Whether a session's recorded native exit has already been answered by a resume.

A headless worker runs one native turn at a time. Between turns its process
exits normally, the machine records that exit, and the next message resumes
the same conversation from its transcript in a new process. The recorded
exit therefore stays on the session row until the resumed process stamps
activity or reports its own exit -- and for that window the row reads as a
dead worker while a live one is starting.

This module names that window from the wake attempts themselves: a wake
started at or after the recorded exit that is still open, or that resumed a
process which has not reported exiting since. Every such resumed process
reports its own exit, which moves the recorded exit past the attempt, so a
finished resume stops counting by construction.

The window is bounded by the same quiet period resume custody uses. Custody
contains a resume that stays silent for ``RESUME_INACTIVITY_SECONDS``, so an
attempt and session that have both been quiet that long are no longer
evidence of a live process -- that bound is what keeps a lost relay report
from protecting a session forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from yoke_contracts.session_control.resume import (
    RESUME_INACTIVITY_SECONDS,
    RESUMED_RUNNING_RESULT,
)
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)
from yoke_contracts.session_control.wake_delivery import (
    NATIVE_RESUME_ACCEPTED_RESULT,
    WAKE_DELIVERED_RESULT,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import parse_timestamp, row_dict

#: The attempt kind a machine relay records for a native resume.
WAKE_RELAY_ATTEMPT_KIND = "wake_relay"

#: Settled codes that mean a resumed process started and has not been
#: reported finished. Every exit, failure, deferral, and skip is absent: none
#: of those leaves a process behind.
RESUMED_PROCESS_RESULTS = frozenset(
    {NATIVE_RESUME_ACCEPTED_RESULT, RESUMED_RUNNING_RESULT, WAKE_DELIVERED_RESULT}
)

#: The projected process state while a wake is bringing an exited native back.
RESUMING_PROCESS_STATE = "resuming"


def resumable_from_transcript(surface: Any, version: Any) -> bool:
    """Whether a message resumes this surface's exited native from its transcript.

    Read from the surface's own declared ``message_stopped`` operation, so
    every harness answers from its manifest-backed capability rather than a
    branch on its name.
    """
    return surface_operation_supported(
        str(surface or ""), str(version or "") or None, "message_stopped"
    )


@dataclass(frozen=True)
class ResumeInFlight:
    """The newest wake that answered this session's recorded exit."""

    session_id: str
    attempt_id: str
    started_at: str
    #: ``open`` while the relay has not reported; otherwise the stored code.
    attempt_state: str

    def describe(self) -> str:
        return (
            f"wake attempt {self.attempt_id} started {self.started_at} "
            f"({self.attempt_state})"
        )


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _in_flight(record: Mapping[str, Any], *, now: datetime) -> bool:
    started = parse_timestamp(record.get("started_at"))
    if started is None:
        return False
    exited = parse_timestamp(record.get("native_process_gone_at"))
    if exited is not None and started < exited:
        return False
    activity = [
        stamp
        for field in ("last_tool_call_at", "last_heartbeat")
        if (stamp := parse_timestamp(record.get(field))) is not None
    ]
    latest = max([started, *activity])
    return now - latest <= timedelta(seconds=RESUME_INACTIVITY_SECONDS)


def resumes_in_flight(
    conn: Any,
    session_ids: Iterable[str],
    *,
    now: datetime,
) -> dict[str, ResumeInFlight]:
    """The in-flight resume of each named session that has one."""
    wanted = sorted({str(session_id) for session_id in session_ids if session_id})
    if not wanted:
        return {}
    marker = _placeholder(conn)
    codes = sorted(RESUMED_PROCESS_RESULTS)
    rows = conn.execute(
        "SELECT a.target_session_id AS session_id, a.attempt_id AS attempt_id, "
        "a.started_at AS started_at, a.completed_at AS completed_at, "
        "a.result_code AS result_code, "
        "hs.native_process_gone_at AS native_process_gone_at, "
        "hs.last_tool_call_at AS last_tool_call_at, "
        "hs.last_heartbeat AS last_heartbeat "
        "FROM session_message_attempts a "
        "JOIN harness_sessions hs ON hs.session_id = a.target_session_id "
        f"WHERE a.attempt_kind = {marker} "
        f"AND a.target_session_id IN ({','.join(marker for _ in wanted)}) "
        "AND (a.completed_at IS NULL "
        f"OR a.result_code IN ({','.join(marker for _ in codes)})) "
        "ORDER BY a.started_at DESC",
        (WAKE_RELAY_ATTEMPT_KIND, *wanted, *codes),
    ).fetchall()
    found: dict[str, ResumeInFlight] = {}
    for row in rows:
        record = row_dict(row)
        session_id = str(record["session_id"])
        if session_id in found or not _in_flight(record, now=now):
            continue
        found[session_id] = ResumeInFlight(
            session_id=session_id,
            attempt_id=str(record["attempt_id"]),
            started_at=str(record["started_at"]),
            attempt_state=(
                "open"
                if record.get("completed_at") is None
                else str(record.get("result_code") or "")
            ),
        )
    return found


def resume_in_flight(
    conn: Any, session_id: str, *, now: datetime
) -> ResumeInFlight | None:
    """One session's in-flight resume, when it has one."""
    return resumes_in_flight(conn, (session_id,), now=now).get(session_id)


def native_process_projection(
    observation: Mapping[str, Any] | None,
    *,
    resume: ResumeInFlight | None,
    surface: Any,
    version: Any,
) -> dict[str, Any] | None:
    """A recorded exit as a reader should act on it.

    A resume that already answered the exit reads ``resuming``; an exit
    stays ``gone`` and says whether a message brings it back.
    """
    if observation is None:
        return None
    if resume is not None:
        return {
            "state": RESUMING_PROCESS_STATE,
            "observed_at": observation.get("observed_at"),
            "resume_started_at": resume.started_at,
            "resume_attempt_id": resume.attempt_id,
        }
    return {
        **observation,
        "resumable_from_transcript": resumable_from_transcript(surface, version),
    }


__all__ = [
    "RESUMED_PROCESS_RESULTS",
    "RESUMING_PROCESS_STATE",
    "ResumeInFlight",
    "WAKE_RELAY_ATTEMPT_KIND",
    "native_process_projection",
    "resumable_from_transcript",
    "resume_in_flight",
    "resumes_in_flight",
]

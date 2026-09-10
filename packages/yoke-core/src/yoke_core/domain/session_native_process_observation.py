"""Durable machine evidence about a session's most recently known process.

The relay can prove that a process it recorded is gone.  That fact is not a
session-end decision when the session still holds authority, but it must stay
visible until something accounts for it.

Two things account for it.  Later activity proves a replacement process took
over.  And a native that exited normally under a session waiting on purpose
is the ordinary end of a headless command rather than a disappearance: that
row is quiet by declaration, and its own reason describes it better than an
alarm does.  Nothing else accounts for anything — a non-zero exit, and an
exit nobody measured, still read as gone whatever wait is declared, because
hiding a crash behind a park is how a dead worker goes unnoticed.

A repeat of the same report accounts for nothing either.  A machine keeps its
record of a dead process until the control plane ends the session, so a
session kept alive by its claims is reported again on every poll.  Stamping
each of those reports with the moment it arrived made one old exit
permanently newer than every later resume, which is exactly how a session
that had demonstrably resumed kept reading as a fresh death.  The stamp
therefore names the death rather than the poll -- the native's own exit time
where the machine read one, and otherwise the time this session's first
report about that same process earned -- so activity since the death can
still supersede it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.session_control.resume import RESUME_RELAY_SETTLEMENT_RESULTS
from yoke_contracts.session_control.wake_delivery import WAKE_DELIVERED_RESULT
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.session_relay_types import SessionRelayError


NATIVE_PROCESS_GONE_AT_COLUMN = "native_process_gone_at"
NATIVE_PROCESS_GONE_EVIDENCE_COLUMN = "native_process_gone_evidence"
NATIVE_PROCESS_OBSERVATION_COLUMN_DDL = "TEXT DEFAULT NULL"
NATIVE_PROCESS_GONE_STATE = "gone"
CLAIMS_HELD_STATUS = "claims_held"
#: The session declared a wait about itself, so its row is resumable state
#: rather than debris — the process being gone does not settle that wait.
PARKED_STATUS = "parked"
#: The session asked the steering role something and no answer has arrived.
#: Ending it would drop the question along with the row that carries it.
AWAITING_SEAT_REPLY_STATUS = "awaiting_seat_reply"
#: What the reporting machine read from the native's own result.  Only a
#: measured zero says the command finished; an exit nobody captured says
#: nothing at all, and is never read as a clean one.
NATIVE_EXIT_CODE_KEY = "exit_code"
NORMAL_NATIVE_EXIT_CODE = 0
#: When the native exited, as the machine read it from the native's own
#: result. Present only for a launch whose diagnostic capture was readable.
NATIVE_EXIT_AT_KEY = "native_exit_at"


def _decoded_evidence(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _process_identity(evidence: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    """What a report names, so a repeat about one death is recognizable."""
    starts = evidence.get("process_start_times")
    return (
        tuple(sorted(str(pid) for pid in evidence.get("pids") or ())),
        tuple(
            sorted(
                f"{pid}:{start}"
                for pid, start in (
                    starts.items() if isinstance(starts, Mapping) else ()
                )
            )
        ),
    )


def _stored_observation(conn: Any, session_id: str) -> tuple[str, dict[str, Any]]:
    """The observation already on this session's row, if it carries one."""
    placeholder = marker(conn)
    row = conn.execute(
        f"SELECT {NATIVE_PROCESS_GONE_AT_COLUMN} AS observed_at, "
        f"{NATIVE_PROCESS_GONE_EVIDENCE_COLUMN} AS evidence "
        f"FROM harness_sessions WHERE session_id={placeholder}",
        (session_id,),
    ).fetchone()
    if row is None:
        return "", {}
    record = row_dict(row)
    return (
        str(record.get("observed_at") or ""),
        _decoded_evidence(record.get("evidence")),
    )


def _exited_normally(evidence: Mapping[str, Any]) -> bool:
    """Whether the machine measured a native that finished its command."""
    code = evidence.get(NATIVE_EXIT_CODE_KEY)
    if isinstance(code, bool) or not isinstance(code, int):
        return False
    return code == NORMAL_NATIVE_EXIT_CODE


def record_native_process_gone(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Record a relay's verified-dead process evidence without committing.

    The stamp belongs to the death rather than to the report, and which death
    the row describes is decided before anything is written.

    A report about the process already recorded is the same death said again.
    Its own exit time, once the machine has read one, *corrects* the stamp an
    earlier report had to guess from its own arrival; with no exit time it
    keeps the time that first report earned.

    A report about a different process is a different death, and the row
    describes one.  The later death is the one that matters, so a report
    whose death predates what the row already carries is dropped whole --
    stamp and evidence together.  Keeping only its evidence would replace a
    crash with some older native's clean exit, which a declared wait then
    reads as accounted for.
    """
    stored_at, stored_evidence = _stored_observation(conn, session_id)
    identity = _process_identity(evidence)
    exited_at = parse_timestamp(evidence.get(NATIVE_EXIT_AT_KEY))
    death = timestamp(exited_at or observed_at or utc_now())
    if any(identity) and _process_identity(stored_evidence) == identity:
        stamp = death if exited_at is not None else (stored_at or death)
    elif stored_at and death < stored_at:
        return {
            "state": NATIVE_PROCESS_GONE_STATE,
            "observed_at": stored_at,
            "evidence": stored_evidence,
        }
    else:
        stamp = death
    payload = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"))
    placeholder = marker(conn)
    conn.execute(
        f"UPDATE harness_sessions SET {NATIVE_PROCESS_GONE_AT_COLUMN}={placeholder}, "
        f"{NATIVE_PROCESS_GONE_EVIDENCE_COLUMN}={placeholder} "
        f"WHERE session_id={placeholder}",
        (stamp, payload, session_id),
    )
    return {
        "state": NATIVE_PROCESS_GONE_STATE,
        "observed_at": stamp,
        "evidence": dict(evidence),
    }


def settlement_process_evidence(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Identity a wake-settlement report can record without the pid allowlist."""
    source = dict(evidence or {})
    payload: dict[str, Any] = {}
    pid = source.get("native_pid")
    if isinstance(pid, int) and pid > 0:
        payload["native_pid"] = pid
        payload["pids"] = [pid]
        start = source.get("process_start_time")
        if start:
            payload["process_start_times"] = {str(pid): str(start)}
    for key in (NATIVE_EXIT_CODE_KEY, NATIVE_EXIT_AT_KEY):
        if key in source:
            payload[key] = source[key]
    reason = source.get("containment_reason")
    if isinstance(reason, str) and reason.strip():
        payload["containment_reason"] = reason.strip()
    return payload


def absorb_completed_wake_report(
    conn: Any,
    attempt_id: str,
    row: Any,
    incoming_code: str,
    incoming_evidence: Mapping[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    """Keep ``wake_delivered`` and record a later native-exit settlement."""
    stored_code = str(row[2] or "")
    if stored_code == incoming_code:
        return {"attempt_id": attempt_id, "result_code": incoming_code}
    if (
        stored_code != WAKE_DELIVERED_RESULT
        or incoming_code not in RESUME_RELAY_SETTLEMENT_RESULTS
    ):
        raise SessionRelayError("report_conflict", "wake attempt was already reported")
    placeholder = marker(conn)
    conn.execute(
        f"UPDATE session_message_attempts SET evidence={placeholder} "
        f"WHERE attempt_id={placeholder}",
        (merge_redacted_evidence(row[3], incoming_evidence), attempt_id),
    )
    session_id = str(row[5] or "")
    if session_id:
        record_native_process_gone(
            conn,
            session_id,
            settlement_process_evidence(incoming_evidence),
            observed_at=parse_timestamp(now),
        )
    conn.commit()
    return {"attempt_id": attempt_id, "result_code": stored_code}


def current_native_process_observation(
    row: Mapping[str, Any],
    *,
    landing_wait: bool = False,
) -> dict[str, Any] | None:
    """Return process-gone evidence unless something accounts for the death.

    ``landing_wait`` is the caller's ``item_awaiting_landing`` fact from the
    holdings it already loaded; the parked half of the same question is on
    the row itself.  It defaults to the alerting side, so a caller that never
    asked cannot silence an alarm by omission.
    """
    observed = parse_timestamp(row.get(NATIVE_PROCESS_GONE_AT_COLUMN))
    if observed is None:
        return None
    activity = [
        parsed
        for field in ("last_heartbeat", "last_tool_call_at", "episode_started_at")
        if (parsed := parse_timestamp(row.get(field))) is not None
    ]
    # Timestamps have second precision. Equal stamps can be the report and
    # the episode that just died; only strictly later activity proves a
    # replacement process or subsequent tool call.
    if activity and max(activity) > observed:
        return None
    evidence = _decoded_evidence(row.get(NATIVE_PROCESS_GONE_EVIDENCE_COLUMN))
    if (landing_wait or session_is_parked(row.get("mode"))) and _exited_normally(
        evidence
    ):
        return None
    return {
        "state": NATIVE_PROCESS_GONE_STATE,
        "observed_at": str(row.get(NATIVE_PROCESS_GONE_AT_COLUMN) or ""),
        "evidence": evidence,
    }


__all__ = [
    "AWAITING_SEAT_REPLY_STATUS",
    "CLAIMS_HELD_STATUS",
    "NATIVE_EXIT_AT_KEY",
    "NATIVE_EXIT_CODE_KEY",
    "NATIVE_PROCESS_GONE_AT_COLUMN",
    "NATIVE_PROCESS_GONE_EVIDENCE_COLUMN",
    "NATIVE_PROCESS_GONE_STATE",
    "NATIVE_PROCESS_OBSERVATION_COLUMN_DDL",
    "NORMAL_NATIVE_EXIT_CODE",
    "PARKED_STATUS",
    "current_native_process_observation",
    "record_native_process_gone",
    "absorb_completed_wake_report",
    "settlement_process_evidence",
]

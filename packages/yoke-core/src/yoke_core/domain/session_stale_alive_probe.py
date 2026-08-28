"""Ask a silent claim-holder to report, then act on whether it answers.

Two failure modes look identical from the control plane: a session whose
process died, and a session whose process is fine but whose turn has stopped
advancing. Both hold their claims and both go quiet. The machine's own relay
separates them for the first case only — it proves a recorded pid is gone and
that session is ended, which is the right recovery for a dead process.

What is left over is the harder population: claim-holding sessions that read
``stale`` while the relay does *not* prove them dead. Nothing decides anything
about those today, so their claims sit until the holdings TTL expires hours
later, and the work they were holding is blocked the whole time on a session
that may simply be waiting for someone to say something to it.

So ask. The escalation this module opens is deliberately the mildest thing
that could work, in three steps that each only fire when the previous one
produced no answer:

1. **Probe.** Send the session an ordinary message asking it to report. If
   its hooks still run, the message injects, the session takes a turn, and
   the whole question is answered by the recovery itself.
2. **Wake.** A probe nobody collects is a starved envelope like any other,
   so the existing wake machinery escalates it — the native resume when the
   session reads active, the ordinary idle route while it reads stale.
3. **End.** A probe that was *delivered*, then produced no tool call one
   further window later, has had every chance a live process would have
   taken. Ending it releases the claims immediately rather than leaving them
   for the holdings TTL, and carries the probe and wake evidence so the
   verdict can be questioned afterwards.

Delivery is the hinge of that last step, and it is not the same fact as
having woken the session. A wake that resumed a session whose turn then ran
no tool call injects nothing, and three such wakes against one parked
session look — from wake attempts alone — exactly like a session that was
asked three times and refused to answer. It was never asked. So a probe the
receipt does not show as delivered ends nothing: the verdict falls back to
the holdings TTL, which costs time, rather than to ending a session that was
never reached, which costs its work.

Nothing here pages an operator. Each step is evidence for the next, and the
session can end the sequence at any point simply by calling a tool.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence

from yoke_contracts.session_control.liveness import LIVENESS_STALE
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.session_message_types import parse_timestamp, row_dict, utc_now
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.session_mode import SESSION_MODE_PARKED
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_render_end import end_session


#: Marks a message as a status probe. Carried on the message's idempotency
#: key, which is already unique per sender and needs no new column, so the
#: probe is identifiable for the rest of its life from the row itself.
PROBE_KEY_PREFIX = "stale-alive-probe:"

#: The end reason recorded when a probed session never answers.
PROBE_UNRESPONSIVE_REASON = "probe_unresponsive"

#: Why a probed session was left alone: the probe never reached it, so its
#: silence is the wake route's failure and not the session's answer.
PROBE_UNDELIVERED_STATUS = "wake_never_delivered"

PROBE_BODY = (
    "Status probe: this session holds an active work claim but has not made "
    "a tool call since it went quiet, and its machine cannot confirm the "
    "process is gone. Report status by continuing your work — any tool call "
    "clears this probe. If you are blocked or waiting on someone, say so and "
    "release the claim if the work has been handed off. A session that never "
    "answers is ended so its claims return to the fleet."
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def probe_key(session_id: str) -> str:
    """Return the marker one session's probe carries."""
    return f"{PROBE_KEY_PREFIX}{session_id}"


def _claim_holding_quiet_sessions(
    conn: Any,
    *,
    machine_id: str,
    projects: Sequence[int],
) -> List[Dict[str, Any]]:
    """Return this machine's live, claim-holding sessions in its projects."""
    if not projects:
        return []
    marker = _p(conn)
    placeholders = ",".join(marker for _ in projects)
    rows = conn.execute(
        "SELECT DISTINCT hs.session_id,hs.project_id,hs.actor_id,hs.executor,"
        "hs.machine_id,hs.last_heartbeat,hs.last_tool_call_at,hs.ended_at,"
        "hs.terminated_at,hs.mode "
        "FROM harness_sessions hs JOIN work_claims wc "
        "ON wc.session_id=hs.session_id AND wc.released_at IS NULL "
        f"WHERE hs.machine_id={marker} AND hs.ended_at IS NULL "
        f"AND hs.terminated_at IS NULL AND hs.project_id IN ({placeholders}) "
        "ORDER BY hs.session_id",
        (machine_id, *projects),
    ).fetchall()
    return [row_dict(row) for row in rows]


def _has_live_probe(conn: Any, session_id: str, *, now: datetime) -> bool:
    """True while an earlier probe is still pending or injected.

    The resume a starved probe triggers spawns a real process, so a second
    probe racing the first is the failure this guards. One live probe at a
    time also keeps the answer unambiguous: whatever the session does next
    is a response to exactly one question.
    """
    marker = _p(conn)
    from yoke_core.domain.session_message_types import timestamp

    return (
        conn.execute(
            "SELECT 1 FROM session_message_recipients r "
            "JOIN session_messages m ON m.message_id=r.message_id "
            f"WHERE r.session_id={marker} AND m.idempotency_key={marker} "
            "AND r.state IN ('pending','injected') AND m.cancelled_at IS NULL "
            f"AND m.expires_at>{marker} LIMIT 1",
            (session_id, probe_key(session_id), timestamp(now)),
        ).fetchone()
        is not None
    )


def _send_probe(conn: Any, row: Dict[str, Any]) -> str | None:
    """Send one probe; return a named status when it could not be sent."""
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_message_service import send_message
    from yoke_core.domain.session_message_authorization import SessionMessageError

    actor_id = row.get("actor_id")
    if actor_id is None:
        # The probe is sent on the authority of whoever owns the session's
        # work, so a session with no actor has nobody to ask on its behalf.
        return "actor_unknown"
    session_id = str(row["session_id"])
    try:
        send_message(
            conn,
            actor_id=int(actor_id),
            sender_session_id=None,
            selector=RecipientSelector(session_ids=[session_id]),
            body=PROBE_BODY,
            idempotency_key=probe_key(session_id),
        )
    except SessionMessageError as exc:
        return f"refused_{exc.code.lower()}"
    return None


def probe_stale_alive_sessions(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Probe this machine's quiet claim-holders that are not proven dead.

    A session reported process-dead has already been ended by the relay's
    own liveness path, so a row that still reads ``stale`` here is one the
    machine could not prove dead — alive, or unknown, which for this purpose
    are the same answer: worth asking.
    """
    current = now or utc_now()
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    probed: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for row in _claim_holding_quiet_sessions(
        conn, machine_id=machine_id, projects=projects
    ):
        session_id = str(row["session_id"])
        if str(row.get("mode") or "") == SESSION_MODE_PARKED:
            continue
        if session_liveness(row, now=current) != LIVENESS_STALE:
            continue
        # The probe threshold is time spent stale, not time spent quiet.
        # Quiet is already what staleness measures, and its TTL varies by
        # executor — an hour for the long-lived desktop threads — so a
        # threshold counted from the last tool call would sit below that TTL
        # for some executors and above it for others, and mean nothing in
        # either case. Asking whether the session was already stale a
        # threshold ago reuses the same executor-aware predicate and gives
        # the knob one meaning everywhere.
        threshold = timedelta(
            seconds=project_policy(
                conn, int(row["project_id"])
            ).stale_alive_probe_seconds
        )
        if not activity_is_stale(
            max(
                str(row.get("last_heartbeat") or ""),
                str(row.get("last_tool_call_at") or ""),
            ),
            executor=row.get("executor"),
            now=current - threshold,
        ):
            continue
        if _has_live_probe(conn, session_id, now=current):
            continue
        status = _send_probe(conn, row)
        if status is None:
            probed.append(session_id)
        else:
            skipped.append({"session_id": session_id, "status": status})
    return {"probed": probed, "skipped": skipped}


def _unanswered_probes(
    conn: Any,
    *,
    machine_id: str,
    projects: Sequence[int],
    now: datetime,
) -> List[Dict[str, Any]]:
    """Return probes that were woken and still produced no tool call."""
    if not projects:
        return []
    marker = _p(conn)
    placeholders = ",".join(marker for _ in projects)
    rows = conn.execute(
        "SELECT r.session_id,r.wake_attempt_count,r.last_wake_at,r.state,"
        "r.injection_count,r.last_injected_at,"
        "m.message_id,m.created_at AS probe_created_at,hs.project_id,"
        "hs.last_tool_call_at,hs.mode "
        "FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "JOIN harness_sessions hs ON hs.session_id=r.session_id "
        f"WHERE m.idempotency_key LIKE {marker} AND m.cancelled_at IS NULL "
        f"AND hs.machine_id={marker} AND hs.ended_at IS NULL "
        f"AND hs.terminated_at IS NULL AND hs.project_id IN ({placeholders}) "
        "AND r.wake_attempt_count>0 "
        "ORDER BY r.session_id,m.created_at",
        (f"{PROBE_KEY_PREFIX}%", machine_id, *projects),
    ).fetchall()
    return [row_dict(row) for row in rows]


def end_probe_unresponsive_sessions(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """End sessions that were probed, then woken, and still said nothing.

    The claims are released with the end, because the whole reason to reach
    this step is that they are being held by something that has stopped
    answering for them.
    """
    current = now or utc_now()
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    ended: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for row in _unanswered_probes(
        conn, machine_id=machine_id, projects=projects, now=current
    ):
        session_id = str(row["session_id"])
        if str(row.get("mode") or "") == SESSION_MODE_PARKED:
            continue
        probe_sent = parse_timestamp(row.get("probe_created_at"))
        last_wake = parse_timestamp(row.get("last_wake_at"))
        if probe_sent is None or last_wake is None:
            continue
        last_tool_call = parse_timestamp(row.get("last_tool_call_at"))
        if last_tool_call is not None and last_tool_call > probe_sent:
            # It answered. The probe having been woken says nothing once a
            # turn actually ran.
            continue
        if int(row.get("injection_count") or 0) < 1:
            # Woken but never handed the probe. Nothing here is evidence
            # about the session; it is evidence about the wake route.
            skipped.append(
                {"session_id": session_id, "status": PROBE_UNDELIVERED_STATUS}
            )
            continue
        window = timedelta(
            seconds=project_policy(conn, int(row["project_id"])).wake_ack_grace_seconds
        )
        if last_wake + window > current:
            continue
        evidence = {
            "source": "stale_alive_probe",
            "verdict": PROBE_UNRESPONSIVE_REASON,
            "probe_message_id": str(row["message_id"]),
            "probe_sent_at": str(row.get("probe_created_at") or ""),
            "probe_state": str(row.get("state") or ""),
            "probe_injected_at": str(row.get("last_injected_at") or ""),
            "wake_attempt_count": int(row.get("wake_attempt_count") or 0),
            "last_wake_at": str(row.get("last_wake_at") or ""),
        }
        try:
            end_session(
                conn,
                session_id,
                release_claims=True,
                # A session that did not answer its probe cannot take the
                # next chain step either; the rationale rides the ledger.
                override_chain_end=True,
                chain_end_rationale=PROBE_UNRESPONSIVE_REASON,
                end_reason=PROBE_UNRESPONSIVE_REASON,
                agent_presence_evidence=evidence,
            )
        except SessionError as exc:
            skipped.append(
                {"session_id": session_id, "status": f"refused_{exc.code.lower()}"}
            )
            continue
        ended.append(session_id)
    return {"ended": ended, "skipped": skipped}


__all__ = [
    "PROBE_BODY",
    "PROBE_KEY_PREFIX",
    "PROBE_UNDELIVERED_STATUS",
    "PROBE_UNRESPONSIVE_REASON",
    "end_probe_unresponsive_sessions",
    "probe_key",
    "probe_stale_alive_sessions",
]

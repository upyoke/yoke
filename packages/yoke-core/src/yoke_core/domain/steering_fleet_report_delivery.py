"""Decide whether this delivery carries the fleet report, and stamp that it did.

The report needs no producer of its own. Workers already message their steerer
as ordinary traffic, and every one of those messages is a wake that runs the
steering session's hooks — so the report rides the envelope that is already on
its way and reaches every harness through the delivery plane they all share.
Nothing here schedules, ticks, or polls. The standing fleet watcher separately
checks due reports during quiet periods, when timer-only findings can appear.

Both deliver through one record per session — ``last_steering_report_at`` and
``last_steering_report_fingerprint`` on ``harness_sessions`` — so a report
the hook attached is not printed again by the watcher, and the reverse.

Two gates keep that ride cheap and quiet. Composition is real work — it ranks
the project's schedule — so it happens at most once per interval per steering
session. A composed report is only attached when the picture changed since
the last one they saw, including changes to outstanding decisions.
The failure mode being avoided is specific: a report that keeps
arriving with nothing in it becomes a report the steerer learns to skim, and
then the one that mattered is skimmed too.
"""

from __future__ import annotations

from yoke_core.domain.db_helpers import instant_parameter

from yoke_contracts.timestamps import parse_instant, utc_now

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
)
from yoke_core.domain import db_backend
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.steering_claims import list_session_claims
from yoke_core.domain.steering_fleet_report_compose import compose_held_reports
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _policy_minutes(conn: Any, project_id: int, key: str, default: int) -> int:
    try:
        return max(1, int(project_policy_value(conn, project_id, key, default)))
    except (TypeError, ValueError):
        return default


def steered_project_id(conn: Any, session_id: str) -> int | None:
    """A project_id from this session's live steering claims, if any."""
    held = _held_project_ids(conn, session_id)
    return held[0] if held else None


def _last_report(conn: Any, session_id: str) -> tuple[datetime | None, str]:
    row = conn.execute(
        "SELECT last_steering_report_at, last_steering_report_fingerprint "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        return (None, "")
    record = dict(row)
    return (
        parse_instant(record["last_steering_report_at"])
        if record.get("last_steering_report_at") is not None
        else None,
        str(record.get("last_steering_report_fingerprint") or ""),
    )


def _claim_interval(
    conn: Any,
    *,
    session_id: str,
    now: datetime,
    not_after: datetime,
    fingerprint: str,
) -> bool:
    """Take this session's report interval, or report that someone else did.

    Compare-and-set rather than read-then-write: two hook deliveries for one
    session can lease at the same moment, and the loser must attach nothing
    rather than repeat what the winner is already carrying.
    """
    now = parse_instant(now)
    marker = _p(conn)
    cursor = conn.execute(
        "UPDATE harness_sessions SET last_steering_report_at = "
        + marker
        + ", last_steering_report_fingerprint = "
        + marker
        + " WHERE session_id = "
        + marker
        + " AND (last_steering_report_at IS NULL "
        "OR last_steering_report_at <= " + marker + ")",
        (
            instant_parameter(conn, now),
            fingerprint,
            session_id,
            instant_parameter(conn, parse_instant(not_after)),
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


def _held_project_ids(conn: Any, session_id: str) -> tuple[int, ...]:
    ids: list[int] = []
    for claim in list_session_claims(conn, session_id=session_id, active_only=True):
        raw = dict(claim.get("scope") or {}).get("project_id")
        if raw is None:
            continue
        ids.append(int(raw))
    return tuple(ids)


@dataclass(frozen=True)
class SteeringReportCandidate:
    """A composed report this session is owed, pending confirmed delivery.

    Composition and eligibility are decided at :func:`steering_report_candidate`
    time; the interval is not spent until :func:`confirm_steering_report_delivery`
    runs, so a reply that turns out denied or malformed leaves the next hook
    free to retry instead of losing this session's report for a whole
    interval to a delivery that never reached the model.
    """

    text: str
    session_id: str
    fingerprint: str
    claimed_at: datetime
    not_after: datetime


def steering_report_candidate(
    conn: Any,
    *,
    session_id: str,
    now: datetime | None = None,
) -> SteeringReportCandidate | None:
    """The report this session is owed right now, without claiming the interval.

    Returns ``None`` for every session that is not steering, for a steering
    session still inside its report interval, and for a report whose content
    does not differ from the one that session last saw
    (that quiet case still takes the interval immediately, exactly as
    before — there is no reply for a sibling denial to drop, since nothing
    is being attached). A genuine report defers its claim to the caller
    confirming the reply actually carried it.
    """
    current = utc_now() if now is None else parse_instant(now)
    project_ids = _held_project_ids(conn, session_id)
    if not project_ids:
        return None
    interval = min(
        _policy_minutes(
            conn,
            project_id,
            "steering_report_interval_minutes",
            DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
        )
        for project_id in project_ids
    )
    not_after = current - timedelta(minutes=interval)
    last_at, last_fingerprint = _last_report(conn, session_id)
    if last_at and last_at > not_after:
        return None

    combined = compose_held_reports(
        conn,
        session_id=session_id,
        now=current,
    )
    fingerprint = combined.fingerprint()
    if fingerprint == last_fingerprint:
        # Nothing new to see. Still take the interval so
        # the next delivery does not pay for the same composition again.
        _claim_interval(
            conn,
            session_id=session_id,
            now=current,
            not_after=not_after,
            fingerprint=fingerprint,
        )
        return None
    return SteeringReportCandidate(
        text=combined_hook_digest(combined),
        session_id=session_id,
        fingerprint=fingerprint,
        claimed_at=current,
        not_after=not_after,
    )


def confirm_steering_report_delivery(
    conn: Any, candidate: SteeringReportCandidate
) -> bool:
    """Claim the interval now that the reply is confirmed to carry the report."""
    return _claim_interval(
        conn,
        session_id=candidate.session_id,
        now=candidate.claimed_at,
        not_after=candidate.not_after,
        fingerprint=candidate.fingerprint,
    )


def record_report_delivery(
    conn: Any, *, session_id: str, fingerprint: str, now: datetime | str
) -> bool:
    """Stamp a report onto this session's record unless it already carries it.

    The fleet watcher's half of the shared record. True means this caller is
    the first to deliver this content and should show it; False means the
    session already received it, from the hook or an earlier watcher pass.
    Compare-and-set suppresses a later watcher once delivery is recorded.
    A narrow race remains: a hook can render its provisional candidate before
    either writer records it, while a watcher records and prints that same
    content before hook settlement. The interval CAS then rejects the hook's
    stamp, but cannot retract its rendered reply. This can duplicate one report;
    the shared fingerprint suppresses subsequent deliveries. Different-content
    candidates can similarly race; this record is not a rendering lock.
    """
    now = parse_instant(now)
    marker = _p(conn)
    cursor = conn.execute(
        "UPDATE harness_sessions SET last_steering_report_at = "
        + marker
        + ", last_steering_report_fingerprint = "
        + marker
        + " WHERE session_id = "
        + marker
        + " AND COALESCE(last_steering_report_fingerprint, '') <> "
        + marker,
        (instant_parameter(conn, now), fingerprint, session_id, fingerprint),
    )
    conn.commit()
    return cursor.rowcount == 1


def steering_report_for_delivery(
    conn: Any,
    *,
    session_id: str,
    now: datetime | None = None,
) -> str | None:
    """Compose and immediately confirm delivery in one call.

    The synchronous, single-call shape every direct caller wants. The hook
    delivery port instead defers confirmation until it knows the rendered
    reply actually carried the candidate (see ``steering_report_candidate``).
    """
    candidate = steering_report_candidate(conn, session_id=session_id, now=now)
    if candidate is None:
        return None
    if not confirm_steering_report_delivery(conn, candidate):
        return None
    return candidate.text or None


__all__ = [
    "SteeringReportCandidate",
    "confirm_steering_report_delivery",
    "record_report_delivery",
    "steered_project_id",
    "steering_report_candidate",
    "steering_report_for_delivery",
]

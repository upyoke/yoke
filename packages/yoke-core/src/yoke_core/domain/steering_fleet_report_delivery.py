"""Decide whether this delivery carries the fleet report, and stamp that it did.

The report needs no producer of its own. Workers already message their steerer
as ordinary traffic, and every one of those messages is a wake that runs the
steering session's hooks — so the report rides the envelope that is already on
its way and reaches every harness through the delivery plane they all share.
Nothing here schedules, ticks, or polls: a fleet quiet enough to send no
messages is the same fleet with nothing to report.

Two gates keep that ride cheap and quiet. Composition is real work — it ranks
the project's schedule — so it happens at most once per interval per steering
session. And a composed report is only attached when it is *worth* a read:
something needs the steerer's decision, or the picture changed since the last
one they saw. The failure mode being avoided is specific: a report that keeps
arriving with nothing in it becomes a report the steerer learns to skim, and
then the one that mattered is skimmed too.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
)
from yoke_core.domain import db_backend
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.steering_claims import list_session_claims
from yoke_core.domain.steering_fleet_report_compose import (
    combined_body,
    compose_held_reports,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _policy_minutes(conn: Any, project_id: int, key: str, default: int) -> int:
    try:
        return max(1, int(project_policy_value(conn, project_id, key, default)))
    except (TypeError, ValueError):
        return default


def steered_project_id(conn: Any, session_id: str) -> int | None:
    """A project_id from this session's live steering claims, if any."""
    held = _held_project_ids(conn, session_id)
    return held[0] if held else None


def _last_report(conn: Any, session_id: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT last_steering_report_at, last_steering_report_fingerprint "
        f"FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        return ("", "")
    record = dict(row)
    return (
        str(record.get("last_steering_report_at") or ""),
        str(record.get("last_steering_report_fingerprint") or ""),
    )


def _claim_interval(
    conn: Any,
    *,
    session_id: str,
    now: str,
    not_after: str,
    fingerprint: str,
) -> bool:
    """Take this session's report interval, or report that someone else did.

    Compare-and-set rather than read-then-write: two hook deliveries for one
    session can lease at the same moment, and the loser must attach nothing
    rather than repeat what the winner is already carrying.
    """
    marker = _p(conn)
    cursor = conn.execute(
        "UPDATE harness_sessions SET last_steering_report_at = "
        + marker
        + ", last_steering_report_fingerprint = "
        + marker
        + " WHERE session_id = "
        + marker
        + " AND (last_steering_report_at IS NULL "
        "OR last_steering_report_at = '' "
        "OR last_steering_report_at <= " + marker + ")",
        (now, fingerprint, session_id, not_after),
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


def steering_report_for_delivery(
    conn: Any,
    *,
    session_id: str,
    now: datetime | None = None,
) -> str | None:
    """The report block to append to this session's delivery, or ``None``.

    Returns ``None`` for every session that is not steering, for a steering
    session still inside its report interval, and for a report whose content
    neither needs a decision nor differs from the one that session last saw.
    The attached body covers every scope the session holds.
    """
    project_ids = _held_project_ids(conn, session_id)
    if not project_ids:
        return None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    interval = min(
        _policy_minutes(
            conn,
            project_id,
            "steering_report_interval_minutes",
            DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
        )
        for project_id in project_ids
    )
    not_after = _stamp(current - timedelta(minutes=interval))
    last_at, last_fingerprint = _last_report(conn, session_id)
    if last_at and last_at > not_after:
        return None

    combined = compose_held_reports(
        conn,
        session_id=session_id,
        now=_stamp(current),
    )
    fingerprint = combined.fingerprint()
    if not combined.actionable and fingerprint == last_fingerprint:
        # Nothing to act on and nothing new to see. Still take the interval so
        # the next delivery does not pay for the same composition again.
        _claim_interval(
            conn,
            session_id=session_id,
            now=_stamp(current),
            not_after=not_after,
            fingerprint=fingerprint,
        )
        return None
    if not _claim_interval(
        conn,
        session_id=session_id,
        now=_stamp(current),
        not_after=not_after,
        fingerprint=fingerprint,
    ):
        return None
    return combined_body(combined)


__all__ = ["steered_project_id", "steering_report_for_delivery"]

"""Three failures that arrive as silence, read from live control-plane state.

Each detector answers a question a steering seat used to answer by
remembering to go and look: did a message reach the worker it was sent to,
did a launch ever produce a session, and did merged work ever close out. A
habit is not a guarantee, so they are queries. The fourth silence -- an idle
worker waiting on an answer that cannot arrive -- is a judgment rather than a
lookup and lives in :mod:`steering_fleet_report_dead_waits`.

Time math lives here rather than in the composing module because every reader
of these stamps shares it, and a second parser would be a second set of rules
about what "old" means.

Every query below reads tables the control plane already owns:
``session_message_recipients`` for delivery, ``session_launches`` for
launches, and ``items`` for close-out -- its own ``merged_at`` and
``merge_queue_landed_at`` columns, no new data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES


#: How long an envelope may sit uninjected before the delivery plane has
#: plainly failed rather than merely not finished yet. This is a property of
#: delivery, not a steering judgment, so it is a constant rather than a
#: project policy key an operator would have no basis to tune.
STARVED_DELIVERY_GRACE_SECONDS = 10 * 60


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def parse_stamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def age_seconds(stamp: str | None, now: str) -> int | None:
    """Seconds between ``stamp`` and ``now``, or ``None`` for no stamp."""
    if not stamp:
        return None
    return max(0, int((parse_stamp(now) - parse_stamp(stamp)).total_seconds()))


@dataclass(frozen=True)
class StarvedDelivery:
    """One session with envelopes the delivery plane never injected."""

    session_id: str
    envelope_count: int
    oldest_seconds: int


@dataclass(frozen=True)
class UnregisteredLaunch:
    """One launch past its deadline that never produced a session."""

    launch_id: str
    surface: str
    machine_id: str
    state: str
    overdue_seconds: int


@dataclass(frozen=True)
class LandedItem:
    """One item whose branch landed while the item stayed open."""

    item_id: int
    item_ref: str
    status: str
    landed_at: str
    landed_seconds: int


def starved_deliveries(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[StarvedDelivery, ...]:
    """Envelopes still pending and never injected, whose recipient went quiet.

    Sender is deliberately not a filter: a worker-to-worker envelope starves
    exactly like a steerer-sent one. Ended and terminated recipients are
    excluded -- an envelope addressed to a session that is gone is not a
    worker waiting on a message, and there is nothing left to revive.

    Grouped by recipient because the action is per recipient: one session
    with four stuck envelopes is one worker to wake, not four findings.
    """
    p = marker(conn)
    rows = conn.execute(
        f"""SELECT r.session_id AS session_id,
                   r.created_at AS created_at,
                   s.last_tool_call_at AS last_tool_call_at
              FROM session_message_recipients r
              JOIN harness_sessions s ON s.session_id = r.session_id
             WHERE r.state = 'pending'
               AND COALESCE(r.injection_count, 0) = 0
               AND r.project_id = {p}
               AND s.ended_at IS NULL
               AND s.terminated_at IS NULL""",
        (int(project_id),),
    ).fetchall()
    oldest: dict[str, int] = {}
    counts: dict[str, int] = {}
    for row in rows:
        record = dict(row)
        sent_at = str(record.get("created_at") or "")
        waited = age_seconds(sent_at, now)
        if waited is None or waited < STARVED_DELIVERY_GRACE_SECONDS:
            continue
        acted = str(record.get("last_tool_call_at") or "")
        if acted and parse_stamp(acted) >= parse_stamp(sent_at):
            # The recipient has run a tool since the send, so this envelope is
            # that session's ordinary backlog rather than a stuck delivery.
            continue
        session_id = str(record["session_id"])
        counts[session_id] = counts.get(session_id, 0) + 1
        oldest[session_id] = max(oldest.get(session_id, 0), waited)
    return tuple(
        StarvedDelivery(
            session_id=session_id,
            envelope_count=counts[session_id],
            oldest_seconds=oldest[session_id],
        )
        for session_id in sorted(oldest, key=lambda key: (-oldest[key], key))
    )


def unregistered_launches(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[UnregisteredLaunch, ...]:
    """Launches past ``deadline_at`` that never bound a session.

    Only launches still in flight are reported. One the deadline sweep has
    already closed needs no reconcile, and including closed launches would
    grow this section with the project's whole launch history.
    """
    p = marker(conn)
    states = sorted(IN_FLIGHT_LAUNCH_STATES)
    holes = ", ".join(p for _ in states)
    rows = conn.execute(
        f"""SELECT launch_id, selected_surface, requested_surface,
                   assigned_machine_id, requested_machine_id, state, deadline_at
              FROM session_launches
             WHERE registered_session_id IS NULL
               AND project_id = {p}
               AND state IN ({holes})
             ORDER BY deadline_at ASC, launch_id ASC""",
        (int(project_id), *states),
    ).fetchall()
    overdue = []
    for row in rows:
        record = dict(row)
        elapsed = age_seconds(str(record.get("deadline_at") or ""), now)
        if not elapsed:
            continue
        overdue.append(
            UnregisteredLaunch(
                launch_id=str(record["launch_id"]),
                surface=str(
                    record.get("selected_surface")
                    or record.get("requested_surface")
                    or "unknown"
                ),
                machine_id=str(
                    record.get("assigned_machine_id")
                    or record.get("requested_machine_id")
                    or "unassigned"
                ),
                state=str(record.get("state") or ""),
                overdue_seconds=elapsed,
            )
        )
    return tuple(overdue)


def landed_without_closeout(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[LandedItem, ...]:
    """Items whose branch landed while the item never reached a terminal status.

    The landing stamp is the item's own ``merged_at`` or, on a merge-queue
    project, ``merge_queue_landed_at``; the earlier of the two present is the
    moment the code was on the base branch.
    """
    p = marker(conn)
    terminal = sorted(TERMINAL_STATUSES)
    holes = ", ".join(p for _ in terminal)
    rows = conn.execute(
        f"""SELECT id, status, merged_at, merge_queue_landed_at
              FROM items
             WHERE project_id = {p}
               AND status NOT IN ({holes})
               AND (merged_at IS NOT NULL OR merge_queue_landed_at IS NOT NULL)""",
        (int(project_id), *terminal),
    ).fetchall()
    records = [dict(row) for row in rows]
    refs = render_item_refs(conn, [int(record["id"]) for record in records])
    landed = []
    for record in records:
        present = [
            str(record.get(name) or "")
            for name in ("merged_at", "merge_queue_landed_at")
            if record.get(name)
        ]
        if not present:
            continue
        landed_at = min(present)
        item_id = int(record["id"])
        landed.append(
            LandedItem(
                item_id=item_id,
                item_ref=refs.get(item_id, str(item_id)),
                status=str(record.get("status") or ""),
                landed_at=landed_at,
                landed_seconds=age_seconds(landed_at, now) or 0,
            )
        )
    return tuple(sorted(landed, key=lambda entry: (-entry.landed_seconds, entry.item_id)))


__all__ = [
    "STARVED_DELIVERY_GRACE_SECONDS",
    "LandedItem",
    "StarvedDelivery",
    "UnregisteredLaunch",
    "age_seconds",
    "landed_without_closeout",
    "marker",
    "parse_stamp",
    "starved_deliveries",
    "unregistered_launches",
]

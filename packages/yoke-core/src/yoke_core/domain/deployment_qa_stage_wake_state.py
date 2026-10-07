"""Whether the owner of a waiting item-QA member has been woken.

A member waiting on item-scoped QA is only progressing if someone who can
supply its evidence knows. The stage driver sends that wake as a
``deployment-qa-stage-wait`` session message; this module reads those
stored notices back, so the fleet report can tell a pending wake from a
missing one without a parallel record.

Three answers, each one line:

* ``wake pending`` — the driver is live and has not sent it yet;
* ``woken HH:MMZ`` — a notice exists, qualified by whether its recipient
  acknowledged it, has it injected, or has not received it yet;
* ``not woken`` — with the reason: the wake failed or expired, nobody is
  addressable, or the driver is gone or stale (re-driving sends it).
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_stage_wake import DEPLOYMENT_QA_STAGE_WAIT_PREFIX
from yoke_core.domain.merge_queue_landing_notice import resolve_lane_recipient
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_types import parse_timestamp


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _get(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _clock(raw: Any) -> str:
    stamp = parse_timestamp(raw)
    return stamp.strftime("%H:%MZ") if stamp is not None else str(raw or "")


def _latest_notice(
    conn: Any, *, run_id: str, stage_name: str, item_id: int
) -> tuple[str, str, str] | None:
    """Sent time, recipient state, and wake escalation of the newest notice.

    Every pinned-target attempt of this run/stage/member shares the key
    prefix, so the newest uncancelled one is the wake the owner would act
    on. A notice with no recipient row reads as state ``""``.
    """
    if not (
        _table_exists(conn, "session_messages")
        and _table_exists(conn, "session_message_recipients")
    ):
        return None
    marker = _p(conn)
    row = conn.execute(
        "SELECT m.created_at AS sent_at, COALESCE(r.state, '') AS state, "
        "COALESCE(r.wake_escalation, '') AS escalation "
        "FROM session_messages m "
        "LEFT JOIN session_message_recipients r ON r.message_id = m.message_id "
        f"WHERE m.cancelled_at IS NULL AND m.idempotency_key LIKE {marker} "
        "ORDER BY m.created_at DESC LIMIT 1",
        (f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{stage_name}:{int(item_id)}:%",),
    ).fetchone()
    if row is None:
        return None
    return (
        str(_get(row, "sent_at", 0) or ""),
        str(_get(row, "state", 1) or ""),
        str(_get(row, "escalation", 2) or ""),
    )


def member_wake_state(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    item_id: int,
    project_id: int,
    driver_live: bool,
) -> str:
    """One line saying whether this waiting member's owner was woken."""
    notice = _latest_notice(conn, run_id=run_id, stage_name=stage_name, item_id=item_id)
    if notice is not None:
        sent_at, state, escalation = notice
        sent = _clock(sent_at)
        if state == "acknowledged":
            return f"woken {sent}, acknowledged"
        if state == "injected":
            return f"woken {sent}, not acknowledged"
        if state == "expired":
            return f"not woken: the wake sent {sent} expired undelivered"
        if escalation:
            return f"not woken: the wake sent {sent} failed ({escalation})"
        return f"woken {sent}, not yet delivered"
    if driver_live:
        return "wake pending (driver live, not yet sent)"
    session_id, _actor, _route = resolve_lane_recipient(
        conn, item_id=int(item_id), project_id=int(project_id)
    )
    if not session_id:
        return (
            "not woken: no addressable holder (no live claim holder and no "
            "covering steering seat); staff the item"
        )
    return f"not woken: driver gone or stale; re-drive {run_id} to send it"


__all__ = ["member_wake_state"]

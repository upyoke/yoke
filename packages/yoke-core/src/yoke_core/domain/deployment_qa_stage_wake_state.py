"""Whether the owner of each waiting item-QA member has been woken.

A member waiting on item-scoped QA is only progressing if someone who can
supply its evidence knows. The stage driver tells that owner one of two
ways: a ``deployment-qa-stage-wait`` notice for a member still owed
evidence, or a ``deployment-qa-member-failure`` handoff for a member whose
QA failed. This module reads those stored session messages back, so the
fleet report can tell a pending wake from a missing one without a parallel
record.

Three answers, each one line per member:

* ``wake pending`` — the driver is live and has not sent it yet;
* ``woken HH:MMZ`` — a notice exists, qualified by whether its recipient
  acknowledged it, has it injected, or has not received it yet;
* ``not woken`` — with the reason: the wake failed, expired, or was
  cancelled, nobody is addressable, or the driver is gone or stale
  (re-driving sends it).

Reads are bounded per run, not per member: one notice read for the whole
stage, and at most two addressability reads. Inside a member presentation
the notice read covers every presented run at once.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_failure_handoff import FAILURE_HANDOFF_PREFIX
from yoke_core.domain.deployment_qa_stage_wake import DEPLOYMENT_QA_STAGE_WAIT_PREFIX
from yoke_core.domain.merge_queue_landing_notice import addressable_items
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_types import parse_timestamp

#: Recipient states best-first, so one message with several receipts reads
#: as the furthest any recipient got; ties break on session id.
_STATE_RANK = {
    "acknowledged": 0,
    "injected": 1,
    "pending": 2,
    "expired": 3,
    "cancelled": 4,
}

_FAILURE_HANDOFF = "QA failure handoff"
_WAIT = "wake"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _get(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _clock(raw: Any) -> str:
    stamp = parse_timestamp(raw)
    return stamp.strftime("%H:%MZ") if stamp is not None else "unknown"


def _member_of(key: str, prefixes: dict[str, str]) -> tuple[int, str] | None:
    for prefix, kind in prefixes.items():
        if key.startswith(prefix):
            member = key[len(prefix) :].split(":", 1)[0]
            try:
                return int(member), kind
            except ValueError:
                return None
    return None


def _notice_rows(conn: Any, *, run_id: str, stage_name: str) -> list[Any]:
    """Stored wake notices, newest first, for every presented run at once.

    Inside a member presentation one read covers every presented run's
    stages; callers keep only their own stage's prefixes.
    """
    from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    runs = presented_run_ids(conn, run_id)
    scopes = [f"{run}:" for run in runs] if runs else [f"{run_id}:{stage_name}:"]
    patterns = tuple(
        f"{prefix}{scope}%"
        for scope in scopes
        for prefix in (DEPLOYMENT_QA_STAGE_WAIT_PREFIX, FAILURE_HANDOFF_PREFIX)
    )
    marker = _p(conn)

    def read() -> list[Any]:
        return conn.execute(
            "SELECT m.message_id AS message_id, m.idempotency_key AS idempotency_key, "
            "m.created_at AS sent_at, COALESCE(r.session_id, '') AS session_id, "
            "CASE WHEN m.cancelled_at IS NOT NULL THEN 'cancelled' "
            "ELSE COALESCE(r.state, '') END AS state, "
            "COALESCE(r.wake_escalation, '') AS escalation "
            "FROM session_messages m "
            "LEFT JOIN session_message_recipients r ON r.message_id = m.message_id "
            f"WHERE ({' OR '.join(f'm.idempotency_key LIKE {marker}' for _ in patterns)}) "
            "ORDER BY m.created_at DESC, (m.cancelled_at IS NULL) DESC, m.message_id",
            patterns,
        ).fetchall()

    return presentation_read(conn, ("qa_wake_notices", patterns), read)


def _latest_notices(
    conn: Any, *, run_id: str, stage_name: str
) -> dict[int, tuple[str, datetime | None, str, str]]:
    """Per member: notice kind, sent time, recipient state, wake escalation.

    The newest notice of either kind describes current wake state, including
    cancellation. A notice with no recipient row reads as state ``""``.
    """
    if not (
        _table_exists(conn, "session_messages")
        and _table_exists(conn, "session_message_recipients")
    ):
        return {}
    prefixes = {
        f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{stage_name}:": _WAIT,
        f"{FAILURE_HANDOFF_PREFIX}{run_id}:{stage_name}:": _FAILURE_HANDOFF,
    }
    rows = _notice_rows(conn, run_id=run_id, stage_name=stage_name)
    newest: dict[int, str] = {}
    best: dict[int, tuple[tuple[int, str], tuple[str, datetime | None, str, str]]] = {}
    for row in rows:
        parsed = _member_of(str(_get(row, "idempotency_key", 1) or ""), prefixes)
        if parsed is None:
            continue
        member, kind = parsed
        message_id = str(_get(row, "message_id", 0))
        if newest.setdefault(member, message_id) != message_id:
            continue
        state = str(_get(row, "state", 4) or "")
        session_id = str(_get(row, "session_id", 3) or "")
        rank = (_STATE_RANK.get(state, len(_STATE_RANK)), session_id)
        if member not in best or rank < best[member][0]:
            best[member] = (
                rank,
                (
                    kind,
                    parse_timestamp(_get(row, "sent_at", 2)),
                    state,
                    str(_get(row, "escalation", 5) or ""),
                ),
            )
    return {member: notice for member, (_rank, notice) in best.items()}


def _describe(notice: tuple[str, datetime | None, str, str]) -> str:
    kind, sent_at, state, escalation = notice
    sent = _clock(sent_at)
    by = f" by {_FAILURE_HANDOFF}" if kind == _FAILURE_HANDOFF else ""
    if state == "acknowledged":
        return f"woken {sent}{by}, acknowledged"
    if state == "injected":
        return f"woken {sent}{by}, not acknowledged"
    if state == "expired":
        return f"not woken: the {kind} sent {sent} expired undelivered"
    if state == "cancelled":
        return f"not woken: the {kind} sent {sent} was cancelled"
    if escalation:
        return f"not woken: the {kind} sent {sent} failed ({escalation})"
    return f"woken {sent}{by}, not yet delivered"


def _addressable(conn: Any, members: list[int], *, project_id: int) -> set[int]:
    """Addressable members; inside a presentation, asked once for every presented one."""
    from yoke_core.domain.deployment_qa_presentation_facts import (
        presented_member_ids,
    )
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    presented = presented_member_ids(conn)
    ask = (
        tuple(presented)
        if presented and set(members) <= set(presented)
        else tuple(members)
    )
    return presentation_read(
        conn,
        ("qa_addressable_members", ask, int(project_id)),
        lambda: addressable_items(conn, item_ids=ask, project_id=project_id),
    )


def member_wake_states(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    item_ids: Iterable[int],
    project_id: int,
    driver_live: bool,
) -> dict[int, str]:
    """One line per waiting member saying whether its owner was woken."""
    members = [int(item_id) for item_id in item_ids]
    notices = _latest_notices(conn, run_id=run_id, stage_name=stage_name)
    states = {m: _describe(notices[m]) for m in members if m in notices}
    unsent = [m for m in members if m not in notices]
    if driver_live:
        states.update({m: "wake pending (driver live, not yet sent)" for m in unsent})
        return states
    reachable = _addressable(conn, unsent, project_id=project_id)
    for member in unsent:
        states[member] = (
            f"not woken: driver gone or stale; re-drive {run_id} to send it"
            if member in reachable
            else "not woken: no addressable holder (no live claim holder and no "
            "covering steering seat); staff the item"
        )
    return states


__all__ = ["member_wake_states"]

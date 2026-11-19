"""Warn a walk's owner before the stale sweep aborts its silent walk.

``reap_stale_plan_executions`` aborts an ``active`` or ``walking`` execution
once its heartbeat is :data:`PLAN_EXECUTION_STALE_SECONDS` old, unless its
live owner is parked. Before that, on the same sweep and from the same rows,
the owner gets one Fleet message once the walk has been silent for
:data:`SILENT_WALK_WARN_SECONDS`. The message names the walk, its Test
Machine, the abort time and the fix: a ``yoke qa mission host-command``
heartbeats the walk, and a walk that no longer needs its host releases it.

The idempotency key carries the heartbeat it warns about: a repeat sweep
does not resend, and a walk that heartbeats and then goes silent again is
warned again. The sweep itself is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from yoke_contracts.timestamps import as_utc, format_instant, parse_instant, utc_now
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_authority import (
    HELD_PLAN_EXECUTION_STATES,
    PLAN_EXECUTION_STALE_SECONDS,
    owning_session_is_parked,
)
from yoke_core.domain.qa_plan_execution_store import marker

#: A walk silent this long warns its owner; the sweep aborts it at 30 minutes.
SILENT_WALK_WARN_SECONDS = 20 * 60
#: Walks the heartbeat rule governs; held walks follow their owner's lifetime.
HEARTBEAT_WALK_STATES = ("active", "walking")


def walk_rows(
    conn: Any,
    *,
    states: Iterable[str],
    session_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Live executions with their owner, item, Test Machine and heartbeat.

    One read serves the sweep (every live state, all owners) and the roster
    (heartbeat states, one page of owners). The Test Machine is the one the
    execution's attached lease names; a walk not yet on a host has none.
    """
    from yoke_core.domain.schema_work_claim_sql import scope_text_sql

    p = marker(conn)
    wanted = sorted(set(states))
    where = f"e.state IN ({','.join([p] * len(wanted))})"
    params: list[Any] = list(wanted)
    if session_ids is not None:
        owners = sorted({str(value) for value in session_ids})
        if not owners:
            return []
        where += f" AND e.session_id IN ({','.join([p] * len(owners))})"
        params.extend(owners)
    machine = scope_text_sql(conn, "wc.scope", "test_machine")
    rows = query_rows(
        conn,
        "SELECT e.id, e.heartbeat_at, e.session_id, e.state, e.actor_id, "
        "COALESCE(e.item_id, e.deployment_member_item_id) AS item_id, "
        f"e.test_machine_lease_id, {machine} AS test_machine "
        "FROM qa_plan_executions e "
        "LEFT JOIN work_claims wc ON wc.id=e.test_machine_lease_id "
        f"WHERE {where} ORDER BY e.created_at, e.id",
        tuple(params),
    )
    return [
        {
            "id": str(row["id"]),
            "heartbeat_at": row["heartbeat_at"],
            "session_id": row["session_id"],
            "state": row["state"],
            "actor_id": row["actor_id"],
            "item_id": row["item_id"],
            "test_machine_lease_id": row["test_machine_lease_id"],
            "test_machine": row["test_machine"],
        }
        for row in rows
    ]


def silent_walks(conn: Any, session_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """Heartbeat-governed walks each roster session owns, for the fleet watcher.

    One batched read per roster page. The watcher decides which are silent
    against its own pass clock and :data:`SILENT_WALK_WARN_SECONDS`.
    """
    from yoke_core.domain.item_ref_render import render_item_ref_lookup
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "qa_plan_executions"):
        return {}
    rows = walk_rows(conn, states=HEARTBEAT_WALK_STATES, session_ids=session_ids)
    refs = render_item_ref_lookup(
        conn, (row["item_id"] for row in rows if row["item_id"] is not None)
    )
    walks: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        walks.setdefault(str(row["session_id"]), []).append(
            {
                "execution_id": row["id"],
                "item": refs(row["item_id"]) if row["item_id"] is not None else None,
                "test_machine": row["test_machine"],
                "heartbeat_at": row["heartbeat_at"],
            }
        )
    return walks


def silent_seconds(heartbeat_at: Any, now: datetime) -> float | None:
    """Seconds since *heartbeat_at*, or ``None`` when no heartbeat exists."""
    if heartbeat_at is None:
        return None
    return (as_utc(now) - parse_instant(heartbeat_at)).total_seconds()


def _owner_ended(conn: Any, session_id: str) -> bool:
    row = query_rows(
        conn,
        f"SELECT ended_at FROM harness_sessions WHERE session_id={marker(conn)}",
        (session_id,),
    )
    return not row or row[0]["ended_at"] is not None


def _notice_body(conn: Any, walk: Mapping[str, Any], silent: float) -> str:
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.qa_plan_execution_reconcile import (
        execution_project,
        subject_flag,
    )
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    item = (
        render_item_ref(conn, int(walk["item_id"]))
        if walk.get("item_id") is not None
        else "a standalone plan"
    )
    host = (
        f"Test Machine {walk['test_machine']}"
        if walk.get("test_machine")
        else "no Test Machine yet"
    )
    abort_at = as_utc(parse_instant(walk["heartbeat_at"])) + timedelta(
        seconds=PLAN_EXECUTION_STALE_SECONDS
    )
    execution = select_plan_execution(conn, str(walk["id"]), lock=False)
    flag = subject_flag(conn, execution, execution_project(conn, execution)[1])
    cancel = (
        " If the walk is no longer needed, cancel it, which also frees its "
        f"host: `yoke qa plan abort {flag} --execution-id {walk['id']} "
        "--reason TEXT`."
    )
    return (
        f"QA walk silent: execution {walk['id']} for {item} ({host}) has sent "
        f"no heartbeat for {int(silent // 60)}m. The stale sweep aborts it at "
        f"{abort_at:%Y-%m-%dT%H:%M}Z and the next waiter takes and resets the "
        "host. If the walk is still working, run its next step through "
        "`yoke qa mission host-command`, which heartbeats it." + cancel
    )


def warn_silent_walk(
    conn: Any,
    walk: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> str | None:
    """Mail the owner of a silent, unshielded walk once per silence.

    Returns the message id, or ``None`` when this walk needs no notice: it is
    held, has heartbeat recently, is past the abort line (the sweep owns it),
    or its owner is parked or ended. Commits the message so a later
    candidate's rollback in the same sweep cannot drop it.
    """
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_message_service import send_message

    if walk.get("state") in HELD_PLAN_EXECUTION_STATES:
        return None
    observed = as_utc(now) if now is not None else utc_now()
    silent = silent_seconds(walk.get("heartbeat_at"), observed)
    if silent is None or not (
        SILENT_WALK_WARN_SECONDS <= silent <= PLAN_EXECUTION_STALE_SECONDS
    ):
        return None
    session_id = str(walk.get("session_id") or "")
    if (
        not session_id
        or walk.get("actor_id") is None
        or _owner_ended(conn, session_id)
        or owning_session_is_parked(conn, walk)
    ):
        return None
    created = send_message(
        conn,
        actor_id=int(walk["actor_id"]),
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[session_id]),
        body=_notice_body(conn, walk, silent),
        idempotency_key=(
            f"qa-walk-silent:{walk['id']}:"
            f"{format_instant(parse_instant(walk['heartbeat_at']))}"
        ),
        idempotency_intent_only=True,
        commit=False,
    )
    conn.commit()
    return str(created["message_id"])


__all__ = [
    "HEARTBEAT_WALK_STATES",
    "SILENT_WALK_WARN_SECONDS",
    "silent_seconds",
    "silent_walks",
    "walk_rows",
    "warn_silent_walk",
]

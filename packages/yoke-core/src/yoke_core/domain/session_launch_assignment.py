"""Resolve structured work-item metadata into a bounded native session name."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.item_terminal_resources import (
    item_is_terminal,
    workflow_pin_schema_present,
)
from yoke_core.domain.project_identity import (
    placeholder,
    render_item_ref,
)
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.session_launch_types import SessionLaunchError


MAX_SESSION_NAME_LENGTH = 160


def refuse_terminal_assigned_item(
    conn: Any,
    *,
    public_ref: str,
    project_id: int,
) -> None:
    """Refuse a new launch when the assigned item is already terminal.

    Membership is ``terminal_stage_ids`` for the pinned runtime, including
    engine-owned cancelled/stopped. Missing pin schema is a no-op so
    identity-only fixtures stay valid, and no item-ref resolve runs there.
    """
    if not workflow_pin_schema_present(conn):
        return
    item_id = resolve_item_ref_or_none(conn, public_ref, project=project_id)
    if item_id is None or item_is_terminal(conn, item_id) is not True:
        return
    raise SessionLaunchError(
        "assignment_item_terminal",
        f"assignment item {public_ref} is already terminal; "
        "launch a current non-terminal item instead",
    )


def lock_assigned_item(conn: Any, *, public_ref: str, project_id: int) -> None:
    """Serialize item creates before reading their idempotency keys or workers."""
    from yoke_core.domain import db_backend

    if not db_backend.connection_is_postgres(conn):
        return
    item_id = resolve_item_ref_or_none(conn, public_ref, project=project_id)
    if item_id is not None:
        conn.execute(
            f"SELECT id FROM items WHERE id={placeholder(conn)} FOR UPDATE", (item_id,)
        )


def refuse_held_assigned_item(
    conn: Any,
    *,
    public_ref: str,
    project_id: int,
) -> None:
    """Refuse existing staffing or a live holder inside the create transaction."""
    if not workflow_pin_schema_present(conn):
        return
    item_id = resolve_item_ref_or_none(conn, public_ref, project=project_id)
    if item_id is None:
        return
    from yoke_contracts.session_control.liveness import live_session_sql
    from yoke_core.domain.refusal_recovery import compose_refusal
    from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
    from yoke_core.domain.sessions_offer_revalidation import holder_session_for_item

    p = placeholder(conn)
    holder = holder_session_for_item(conn, item_id)
    holder_id = str(holder.get("holder_session_id") or "")
    live_holder = (
        holder_id
        and conn.execute(
            f"SELECT 1 FROM harness_sessions s WHERE s.session_id={p} "
            f"AND {live_session_sql('s')}",
            (holder_id,),
        ).fetchone()
        is not None
    )
    ref = render_item_ref(conn, item_id, required=True)
    states = sorted(IN_FLIGHT_LAUNCH_STATES)
    holes = ",".join(p for _ in states)
    launch = conn.execute(
        "SELECT l.launch_id, l.state, "
        f"CASE WHEN {live_session_sql('s')} THEN s.session_id END AS session_id "
        "FROM session_launches l LEFT JOIN harness_sessions s "
        "ON s.session_id=COALESCE(l.registered_session_id,l.native_session_id) "
        f"WHERE l.project_id={p} AND l.session_name LIKE {p} "
        f"AND (l.state IN ({holes}) OR l.state='outcome_unknown' "
        f"OR (s.session_id IS NOT NULL AND {live_session_sql('s')})) "
        "ORDER BY l.created_at, l.launch_id LIMIT 1",
        (project_id, f"{ref}: %", *states),
    ).fetchone()
    if not live_holder and launch is None:
        return
    launch_id = str(launch[0]) if launch else "none (claim-only holder)"
    session_id = (
        holder_id if live_holder else str(launch[2] or "no live registered session")
    )
    state = str(launch[1]) if launch else "active work claim"
    recovery = (
        f"Wake or message session {session_id}; if a fresh worker is required, "
        f"terminate it first with `yoke sessions terminate {session_id} --reason R`"
        if session_id != "no live registered session"
        else f"Wait for launch {launch_id} to register; cancel an unstarted launch "
        f"or run `yoke session-control launch reconcile {launch_id}` "
        "before launching a fresh worker"
    )
    raise SessionLaunchError(
        "item_has_live_worker",
        compose_refusal(
            f"Assignment item {ref} already has a worker",
            evaluated=f"holder session {session_id}; launch {launch_id}; state {state}",
            recovery=recovery,
        ),
    )


def assignment_session_name(
    conn: Any,
    *,
    public_ref: str,
    project_id: int,
) -> str:
    """Return ``PREFIX-N: title`` from authoritative item columns."""
    item_id = resolve_item_ref_or_none(conn, public_ref, project=project_id)
    if item_id is None:
        raise SessionLaunchError(
            "assignment_item_not_found",
            f"assignment item {public_ref!r} was not found; pass a current item ref",
        )
    row = conn.execute(
        f"SELECT project_id,title FROM items WHERE id={placeholder(conn)}",
        (item_id,),
    ).fetchone()
    if row is None or int(row[0]) != int(project_id):
        raise SessionLaunchError(
            "assignment_project_mismatch",
            "assignment item must belong to the launch project",
        )
    title = " ".join(str(row[1] or "").split())
    if not title:
        raise SessionLaunchError(
            "assignment_title_missing",
            "assignment item needs a title before it can launch a session",
        )
    name = f"{render_item_ref(conn, item_id, required=True)}: {title}"
    return name[:MAX_SESSION_NAME_LENGTH]


__all__ = [
    "MAX_SESSION_NAME_LENGTH",
    "assignment_session_name",
    "lock_assigned_item",
    "refuse_held_assigned_item",
    "refuse_terminal_assigned_item",
]

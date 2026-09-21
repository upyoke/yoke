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
    resolve_item_id,
)
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
    item_id = resolve_item_id(conn, public_ref, project=project_id)
    if item_id is None or item_is_terminal(conn, item_id) is not True:
        return
    raise SessionLaunchError(
        "assignment_item_terminal",
        f"assignment item {public_ref} is already terminal; "
        "launch a current non-terminal item instead",
    )


def refuse_held_assigned_item(
    conn: Any,
    *,
    public_ref: str,
    project_id: int,
) -> None:
    """Refuse a launch onto an item another session still holds.

    The worker cannot clear that claim, so delivering the launch only
    stalls. Name the holder and the command that releases its claims.
    Missing pin schema is a no-op so identity-only fixtures stay valid,
    matching ``refuse_terminal_assigned_item``.
    """
    if not workflow_pin_schema_present(conn):
        return
    item_id = resolve_item_id(conn, public_ref, project=project_id)
    if item_id is None:
        return
    from yoke_core.domain.sessions_offer_revalidation import holder_session_for_item

    holder = holder_session_for_item(conn, item_id)
    session_id = str(holder.get("holder_session_id") or "")
    if not session_id:
        return
    raise SessionLaunchError(
        "assignment_item_claimed",
        f"assignment item {public_ref} is already claimed by session "
        f"{session_id}. A launched worker cannot clear that claim. Free it "
        f"with `yoke sessions terminate {session_id} --reason R` "
        "(releases the session's held work claims), then launch.",
    )


def assignment_session_name(
    conn: Any,
    *,
    public_ref: str,
    project_id: int,
) -> str:
    """Return ``PREFIX-N: title`` from authoritative item columns."""
    item_id = resolve_item_id(conn, public_ref, project=project_id)
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
    "refuse_held_assigned_item",
    "refuse_terminal_assigned_item",
]

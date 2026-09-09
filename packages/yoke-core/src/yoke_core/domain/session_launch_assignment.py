"""Resolve structured work-item metadata into a bounded native session name."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.project_identity import (
    placeholder,
    render_item_ref,
    resolve_item_id,
)
from yoke_core.domain.session_launch_types import SessionLaunchError


MAX_SESSION_NAME_LENGTH = 160
_TERMINAL_BINDING_MARK = " is terminal at workflow stage "


def _refuse_terminal_assigned_item(
    conn: Any,
    *,
    item_id: int,
    public_ref: str,
) -> None:
    """Refuse a new launch when the assigned item is already terminal.

    Reuses ``item_binding_runtime_state`` so every pinned workflow terminal
    stage — not a hardcoded done/cancelled pair — matches claim refusal.
    Missing pin schema is a no-op so identity-only fixtures stay valid.
    Non-terminal binding errors stay out of this gate.
    """
    from yoke_core.domain.workflow_item_binding_validation import (
        WorkflowItemBindingError,
        item_binding_runtime_state,
    )

    try:
        item_binding_runtime_state(conn, item_id)
    except WorkflowItemBindingError as exc:
        if _TERMINAL_BINDING_MARK not in str(exc):
            return
        raise SessionLaunchError(
            "assignment_item_terminal",
            f"assignment item {public_ref} is already terminal; "
            "launch a current non-terminal item instead",
        ) from exc


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
    _refuse_terminal_assigned_item(conn, item_id=item_id, public_ref=public_ref)
    name = f"{render_item_ref(conn, item_id, required=True)}: {title}"
    return name[:MAX_SESSION_NAME_LENGTH]


__all__ = ["MAX_SESSION_NAME_LENGTH", "assignment_session_name"]

"""Require an assigned launch to enter its own item before succeeding."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_launch_store import marker
from yoke_core.domain.work_claim_target_sql import scope_int_sql


def launch_work_entered(conn: Any, launch: Any) -> bool:
    """A released claim still proves entry; a claim on another item does not."""
    item_id = launch.item_id
    if item_id is None:
        return True
    p = marker(conn)
    item_scope = scope_int_sql(conn, "scope", "item_id")
    return (
        conn.execute(
            f"SELECT 1 FROM work_claims WHERE session_id={p} "
            f"AND target_kind='item' AND {item_scope}={p} "
            f"AND claimed_at>={p} AND claimed_at<{p} LIMIT 1",
            (
                launch.registered_session_id,
                item_id,
                instant_parameter(conn, launch.launching_at),
                instant_parameter(conn, launch.deadline_at),
            ),
        ).fetchone()
        is not None
    )


def complete_entered_launch(conn: Any, launch: Any, *, now: Any) -> Any:
    """Converge acknowledgement and claim arrival in either order."""
    if launch.state != "awaiting_registration" or not launch.registered_session_id:
        return launch
    from yoke_core.domain.session_launch_registration import complete_launch_for_message

    return (
        complete_launch_for_message(
            conn,
            message_id=launch.message_id,
            session_id=launch.registered_session_id,
            now=now,
            commit=False,
        )
        or launch
    )

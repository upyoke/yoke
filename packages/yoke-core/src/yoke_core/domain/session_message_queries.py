"""Actor-aware Fleet message visibility and listing operations."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.actor_message_recipients import expire_due_actor_recipients
from yoke_core.domain.session_message_authorization import can_read_project
from yoke_core.domain.session_message_reads import (
    list_message_ids,
    message_details,
    recipient_project_ids,
)
from yoke_core.domain.session_message_types import SessionMessageError


def _visible(
    conn: Any,
    details: dict[str, Any],
    *,
    actor_id: int,
    session_id: str | None,
) -> bool:
    if int(details["sender_actor_id"]) == actor_id:
        return True
    if any(
        int(row["actor_id"]) == actor_id
        for row in details.get("actor_recipients", [])
    ):
        return True
    if session_id and any(
        str(row["session_id"]) == session_id for row in details["recipients"]
    ):
        return True
    project_ids = recipient_project_ids(details)
    return bool(project_ids) and all(
        can_read_project(conn, actor_id=actor_id, project_id=project_id)
        for project_id in project_ids
    )


def _actor_receipt(details: dict[str, Any], actor_id: int) -> dict[str, Any]:
    result = dict(details)
    result["actor_receipt"] = next(
        (
            row
            for row in details.get("actor_recipients", [])
            if int(row["actor_id"]) == actor_id
        ),
        None,
    )
    return result


def _expire(conn: Any) -> None:
    from yoke_core.domain.session_message_delivery import expire_due_recipients

    expire_due_recipients(conn)
    if expire_due_actor_recipients(conn):
        conn.commit()


def get_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    session_id: str | None,
) -> dict[str, Any]:
    _expire(conn)
    details = message_details(conn, message_id)
    if not _visible(conn, details, actor_id=actor_id, session_id=session_id):
        raise SessionMessageError(
            "message_forbidden", "message is not visible to the calling actor"
        )
    return _actor_receipt(details, actor_id)


def list_messages(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
    state: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    _expire(conn)
    ids = list_message_ids(
        conn,
        state=state,
        session_id=session_id,
        actor_id=actor_id,
        limit=min(500, max(limit * 4, limit)),
    )
    visible: list[dict[str, Any]] = []
    for message_id in ids:
        details = message_details(conn, message_id)
        if _visible(
            conn,
            details,
            actor_id=actor_id,
            session_id=caller_session_id,
        ):
            visible.append(_actor_receipt(details, actor_id))
        if len(visible) >= limit:
            break
    return visible


__all__ = ["get_message", "list_messages"]

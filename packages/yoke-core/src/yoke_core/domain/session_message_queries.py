"""Caller-relative reads of one Fleet message.

Who may read a message is :mod:`yoke_core.domain.session_message_visibility`;
this module answers a single message read and shapes any message for the
caller who asked -- their own receipt, their state and, when they still owe
one, the acknowledgement command.
"""

from __future__ import annotations

from typing import Any, Sequence

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_message_reads import message_details
from yoke_core.domain.session_message_receipt_expiry import project_due_receipts
from yoke_core.domain.session_message_types import SessionMessageError, utc_now
from yoke_core.domain.session_message_visibility import message_visible


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


_ACK_STATES = frozenset({"injected", "pending"})


def _acknowledgement_command(
    details: dict[str, Any],
    session_id: str | None,
) -> str | None:
    if not session_id:
        return None
    for row in details.get("recipients") or []:
        if str(row.get("session_id")) == session_id and row.get("state") in _ACK_STATES:
            return f"yoke messages acknowledge {details['message_id']}"
    return None


def message_with_actor_context(
    details: dict[str, Any],
    *,
    actor_id: int,
    session_id: str | None,
) -> dict[str, Any]:
    result = _actor_receipt(details, actor_id)
    command = _acknowledgement_command(details, session_id)
    if command:
        result["acknowledgement_command"] = command
    result["state"] = _caller_state(details, actor_id=actor_id, session_id=session_id)
    return result


def _caller_state(
    details: dict[str, Any],
    *,
    actor_id: int,
    session_id: str | None,
) -> str:
    if session_id:
        for row in details.get("recipients") or []:
            if str(row.get("session_id")) == session_id:
                return str(row.get("state") or "")
    for row in details.get("actor_recipients") or []:
        if int(row["actor_id"]) == actor_id:
            return str(row.get("state") or "")
    return str(details.get("state") or "")


def get_message(
    conn: Any,
    *,
    message_id: str,
    actor_id: int,
    session_id: str | None,
    fields: Sequence[str] = (),
    detail: str = "",
) -> dict[str, Any]:
    from yoke_contracts.session_control.message_projection import (
        project_message,
        unknown_message_fields,
    )

    details = message_details(conn, message_id)
    if not message_visible(conn, message_id, actor_id=actor_id, session_id=session_id):
        raise SessionMessageError(
            "message_forbidden", "message is not visible to the calling actor"
        )
    project_due_receipts(details, now=parse_instant(utc_now()))
    message = message_with_actor_context(
        details, actor_id=actor_id, session_id=session_id
    )
    unknown = unknown_message_fields(message, fields)
    if unknown:
        known = ", ".join(sorted(message))
        raise SessionMessageError(
            "message_field_unknown",
            f"no such message field: {', '.join(unknown)}. Accepted fields: {known}.",
        )
    return project_message(message, fields=fields, detail=detail)


__all__ = [
    "get_message",
    "message_with_actor_context",
]

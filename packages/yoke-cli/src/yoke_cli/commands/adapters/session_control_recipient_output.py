"""Combined session and human recipient presentation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def display_recipients(
    session_recipients: Iterable[Mapping[str, Any]],
    actor_recipients: Iterable[Mapping[str, Any]],
    steering_recipient: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every party a message reached: sessions, people, and the seat role.

    The role belongs in the same table as the rest. A message queued for a
    seat has a recipient with a state and a scope, and listing only the
    sessions is what made a correct park read as nothing at all.
    """
    rows: list[dict[str, Any]] = []
    for recipient in session_recipients:
        snapshot = recipient.get("routing_snapshot")
        rows.append(
            {
                **(dict(snapshot) if isinstance(snapshot, Mapping) else {}),
                **dict(recipient),
            }
        )
    rows.extend(dict(recipient) for recipient in actor_recipients)
    if steering_recipient is not None:
        rows.append(dict(steering_recipient))
    return rows


def recipient_count(message: Mapping[str, Any]) -> int:
    return (
        len(message.get("recipients") or [])
        + len(message.get("actor_recipients") or [])
        + (1 if message.get("steering_recipient") else 0)
    )


def recipient_states(message: Mapping[str, Any]) -> set[Any]:
    steering = message.get("steering_recipient")
    rows = [
        *(message.get("recipients") or []),
        *(message.get("actor_recipients") or []),
        *([steering] if steering else []),
    ]
    return {row.get("state") or row.get("liveness") for row in rows}


def recipient_party(row: Mapping[str, Any]) -> Any:
    label = row.get("session_id") or row.get("label")
    if label or row.get("actor_id") is None:
        return label
    return f"actor {row['actor_id']}"


def recipient_project(row: Mapping[str, Any]) -> Any:
    return row.get("project") or row.get("project_id")


def steering_summary(message: Mapping[str, Any]) -> str | None:
    """The one sentence a role-addressed message's own state is worth."""
    steering = message.get("steering_recipient")
    if not isinstance(steering, Mapping):
        return None
    return str(steering.get("summary") or "")


def recipient_surface(row: Mapping[str, Any]) -> Any:
    if row.get("actor_id") is not None:
        return "human inbox"
    return row.get("executor_surface")


__all__ = [
    "display_recipients",
    "recipient_count",
    "recipient_party",
    "recipient_project",
    "recipient_states",
    "recipient_surface",
    "steering_summary",
]

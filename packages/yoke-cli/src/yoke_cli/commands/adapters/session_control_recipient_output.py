"""Combined session and human recipient presentation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def display_recipients(
    session_recipients: Iterable[Mapping[str, Any]],
    actor_recipients: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
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
    return rows


def recipient_count(message: Mapping[str, Any]) -> int:
    return len(message.get("recipients") or []) + len(
        message.get("actor_recipients") or []
    )


def recipient_states(message: Mapping[str, Any]) -> set[Any]:
    rows = [
        *(message.get("recipients") or []),
        *(message.get("actor_recipients") or []),
    ]
    return {row.get("state") or row.get("liveness") for row in rows}


def recipient_party(row: Mapping[str, Any]) -> Any:
    label = row.get("session_id") or row.get("label")
    if label or row.get("actor_id") is None:
        return label
    return f"actor {row['actor_id']}"


def recipient_project(row: Mapping[str, Any]) -> Any:
    return row.get("project") or row.get("project_id")


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
]

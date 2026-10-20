"""Open steering mail no live seat is acting on, named one message at a time.

A role-addressed message waits here when it parked with no covering seat,
or when the seat holding it ended or released its claim before
acknowledging or answering. Cancelled and expired mail is settled and never
appears. Each entry names the message, the item that sent it and the seat
scope that covers it, so the steerer can act on that exact message rather
than on a count.

A covering scope another session could take carries the acquire command
that hands the message over. A scope the reading session already holds
carries no acquire advice: the entry names the message to read instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT, capped
from yoke_core.domain.steering_message_recipients import awaiting_seat_rows
from yoke_core.domain.steering_scope_membership import scope_document


@dataclass(frozen=True)
class AwaitingSeatMessage:
    """One open role-addressed message and the seat scope that covers it."""

    message_id: str
    item_ref: str | None
    scope_label: str
    acquire_command: str
    held: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "item_ref": self.item_ref,
            "scope_label": self.scope_label,
            "acquire_command": self.acquire_command,
            "held": self.held,
        }

    def line(self) -> str:
        origin = self.item_ref or "no item"
        if self.held:
            return (
                f"  {self.message_id}  {origin}  {self.scope_label} (held by this "
                f"session)  read: yoke messages get {self.message_id}"
            )
        return (
            f"  {self.message_id}  {origin}  {self.scope_label}  "
            f"take the seat: {self.acquire_command}"
        )


def acquire_command(scope: Mapping[str, Any]) -> str:
    """The acquire that takes exactly this seat scope."""
    command = f"yoke claims steering acquire --project {int(scope['project_id'])}"
    document = scope_document(scope)
    return f"{command} --doc {document}" if document else command


def read_awaiting_seat(
    conn: Any,
    *,
    project_id: int,
    scope: Mapping[str, Any],
    session_id: str,
    now: datetime,
    reads: Any = None,
) -> tuple[AwaitingSeatMessage, ...]:
    """Every open message this seat scope covers that no live seat acts on."""
    from yoke_core.domain.steering_claims import list_session_claims
    from yoke_core.domain.steering_fleet_report_compose import (
        steering_scope_descriptor,
    )

    rows = awaiting_seat_rows(conn, scope=scope, project_id=project_id, now=now)
    if not rows:
        return ()
    refs = render_item_refs(
        conn,
        [
            int(row["sender_item_id"])
            for row in rows
            if row.get("sender_item_id") is not None
        ],
    )
    held = any(
        dict(claim["scope"]) == dict(scope)
        for claim in list_session_claims(conn, session_id=session_id)
    )
    label = steering_scope_descriptor(conn, scope, reads)
    command = acquire_command(scope)
    return tuple(
        AwaitingSeatMessage(
            message_id=str(row["message_id"]),
            item_ref=(
                refs.get(int(row["sender_item_id"]), str(row["sender_item_id"]))
                if row.get("sender_item_id") is not None
                else None
            ),
            scope_label=label,
            acquire_command=command,
            held=held,
        )
        for row in rows
    )


def awaiting_seat_lines(entries: tuple[AwaitingSeatMessage, ...]) -> list[str]:
    """The section a steerer reads, or nothing when no open mail waits."""
    if not entries:
        return []
    heading = (
        f"{len(entries)} steering message(s) awaiting a seat — open mail no live "
        "seat is acting on; acknowledged, cancelled and expired mail stays out:"
    )
    lines = [entry.line() for entry in entries[:SECTION_LIMIT]]
    return [heading, *capped(lines, len(entries))]


def awaiting_seat_fingerprint(
    entries: tuple[AwaitingSeatMessage, ...],
) -> list[tuple[str, bool]]:
    """Which messages wait and whether their seat is held: no ages, no labels."""
    return sorted((entry.message_id, entry.held) for entry in entries)


__all__ = [
    "AwaitingSeatMessage",
    "acquire_command",
    "awaiting_seat_fingerprint",
    "awaiting_seat_lines",
    "read_awaiting_seat",
]

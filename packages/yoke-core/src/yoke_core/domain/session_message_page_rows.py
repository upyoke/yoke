"""One mailbox page's message summaries, read in a fixed number of statements.

A page names its messages first; this module then reads every message,
receipt, steering row and actor name the page needs with one ``IN (...)``
statement per table, never one per message. The only further reads are
one project-slug lookup per distinct steering scope project on the page.

The summaries match what a single message read shows, including receipts
past their message's expiry, which read as expired here
(:mod:`yoke_core.domain.session_message_receipt_expiry`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from yoke_contracts.session_control.sender_surface import sender_surface_label
from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_core.domain.actor_render import render_actor_names
from yoke_core.domain.session_message_reads import ENGINE_SENDER_LABEL
from yoke_core.domain.session_message_receipt_expiry import project_due_receipts
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.steering_message_recipients import STEERING_KIND, TABLE
from yoke_core.domain.steering_recipient_projection import (
    STORED_COLUMNS,
    steering_recipient_from_row,
)


def _rows(
    conn: Any, sql: str, ids: Sequence[str], *leading: Any
) -> list[dict[str, Any]]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    slots = ",".join(marker for _ in ids)
    return [
        row_dict(row)
        for row in conn.execute(
            sql.format(m=marker, ids=slots), (*leading, *ids)
        ).fetchall()
    ]


def _actor_kinds(conn: Any, actor_ids: set[int]) -> dict[int, str]:
    if not actor_ids:
        return {}
    ordered = sorted(actor_ids)
    rows = _rows(conn, "SELECT id,kind FROM actors WHERE id IN ({ids})", ordered)
    return {int(row["id"]): str(row["kind"]) for row in rows}


def page_summaries(
    conn: Any, message_ids: Sequence[str], *, now: datetime
) -> dict[str, dict[str, Any]]:
    """Summaries for ``message_ids`` keyed by id; unknown ids are absent."""
    ids = list(dict.fromkeys(str(value) for value in message_ids))
    if not ids:
        return {}
    messages = {
        str(row["message_id"]): {**row, "recipients": [], "actor_recipients": []}
        for row in _rows(
            conn,
            "SELECT message_id,sender_actor_id,sender_session_id,body,created_at,"
            "expires_at,cancelled_at,cancellation_reason,sender_surface "
            "FROM session_messages WHERE message_id IN ({ids})",
            ids,
        )
    }
    for row in _rows(
        conn,
        "SELECT message_id,session_id,project_id,org_id,executor_surface,machine_id,"
        "state,created_at,injection_count,last_injected_at,acknowledged_at,"
        "expired_at,cancelled_at,wake_attempt_count "
        "FROM session_message_recipients WHERE message_id IN ({ids}) "
        "ORDER BY message_id,session_id",
        ids,
    ):
        messages[str(row.pop("message_id"))]["recipients"].append(row)
    actor_rows = _rows(
        conn,
        "SELECT message_id,actor_id,state,created_at,read_at,expired_at "
        f"FROM {TABLE} WHERE recipient_kind={{m}} AND message_id IN ({{ids}}) "
        "ORDER BY message_id,actor_id",
        ids,
        ACTOR_KIND,
    )
    senders = {
        int(message["sender_actor_id"])
        for message in messages.values()
        if message["sender_actor_id"] is not None
    }
    names = render_actor_names(
        conn, [*senders, *(int(row["actor_id"]) for row in actor_rows)]
    )
    for row in actor_rows:
        actor_id = int(row["actor_id"])
        row.update({"label": names.get(actor_id), "kind": "human"})
        messages[str(row.pop("message_id"))]["actor_recipients"].append(row)
    from yoke_core.domain.steering_fleet_report_reads import FleetReportReads

    reads = FleetReportReads()
    for row in _rows(
        conn,
        f"SELECT message_id,{STORED_COLUMNS} FROM {TABLE} "
        "WHERE recipient_kind={m} AND message_id IN ({ids})",
        ids,
        STEERING_KIND,
    ):
        messages[str(row["message_id"])]["steering_recipient"] = (
            steering_recipient_from_row(conn, row, reads=reads)
        )
    kinds = _actor_kinds(conn, senders)
    for message in messages.values():
        sender = message["sender_actor_id"]
        message["sender_actor_label"] = (
            ENGINE_SENDER_LABEL if sender is None else names.get(int(sender))
        )
        message["sender_actor_kind"] = (
            None if sender is None else kinds.get(int(sender))
        )
        if message.get("sender_surface") is not None:
            message["sender_surface_label"] = sender_surface_label(
                message["sender_surface"]
            )
        project_due_receipts(message, now=now)
    return {
        message_id: temporal_wire(message) for message_id, message in messages.items()
    }


__all__ = ["page_summaries"]

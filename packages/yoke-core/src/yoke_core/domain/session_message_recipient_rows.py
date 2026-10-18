"""The one write that gives a session its receipt for a message."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_types import ResolvedRecipient
from yoke_core.domain.session_message_recipient_scope import recipient_owner


def insert_session_receipt(
    conn: Any,
    *,
    message_id: str,
    recipient: ResolvedRecipient,
    created_at: datetime,
    wake_after: datetime,
) -> None:
    """Write *recipient*'s pending receipt, reviving a cancelled or expired one.

    A send writes fresh rows; a steering handover may find the seat already
    holding a receipt for the message. A live or acknowledged receipt stays
    exactly as it is; a settled-without-acknowledgement one becomes pending
    again so the hook delivers it like any new send.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO session_message_recipients (message_id, session_id, "
        "project_id, org_id, resolution_evidence, routing_snapshot, executor_surface, "
        "executor_version, machine_id, state, created_at, wake_after) "
        f"VALUES ({', '.join(marker for _ in range(12))}) "
        "ON CONFLICT(message_id, session_id) DO UPDATE SET state='pending', "
        "wake_after=excluded.wake_after, injection_lease_id=NULL, "
        "injection_leased_at=NULL, injection_lease_expires_at=NULL, "
        "expired_at=NULL, cancelled_at=NULL "
        "WHERE session_message_recipients.state IN ('cancelled','expired')",
        (
            message_id,
            recipient.session_id,
            *recipient_owner(recipient.routing_snapshot()),
            json.dumps(sorted(set(recipient.resolution))),
            json.dumps(recipient.routing_snapshot(), sort_keys=True),
            recipient.executor_surface,
            recipient.executor_version,
            recipient.machine_id,
            "pending",
            instant_parameter(conn, created_at),
            instant_parameter(conn, wake_after),
        ),
    )


__all__ = ["insert_session_receipt"]

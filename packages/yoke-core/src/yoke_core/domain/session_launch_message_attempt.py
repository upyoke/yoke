"""Append evidence for first-instruction delivery during launch registration."""

from __future__ import annotations

import json
import uuid
from typing import Any

from yoke_core.domain import db_backend


ATTESTATION_ADAPTER_REVISION = "session-launch-attestation-v1"


def record_launch_instruction_attempt(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    injected: bool,
    occurred_at: str,
) -> None:
    """Record the special first hook through the ordinary attempt ledger."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    values = (
        str(uuid.uuid4()),
        message_id,
        session_id,
        "hook",
        ATTESTATION_ADAPTER_REVISION,
        occurred_at,
        occurred_at,
        "injected" if injected else "render_output_missing",
        json.dumps({"delivery_path": "launch_attestation"}, sort_keys=True),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,adapter_revision,"
        "started_at,completed_at,result_code,evidence) VALUES ("
        + ",".join(marker for _ in values)
        + ")",
        values,
    )


__all__ = ["ATTESTATION_ADAPTER_REVISION", "record_launch_instruction_attempt"]

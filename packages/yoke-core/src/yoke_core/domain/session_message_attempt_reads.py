"""Body-free message-attempt evidence for authorized message reads."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_core.domain import db_backend, json_helper


ATTEMPT_READ_LIMIT = 500


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _evidence(value: Any) -> dict[str, str | int]:
    try:
        decoded = json_helper.loads_text(str(value))
    except (TypeError, ValueError):
        decoded = None
    return redacted_evidence_document(decoded)


def message_attempt_evidence(conn: Any, message_id: str) -> dict[str, Any]:
    """Return bounded attempt facts without leases or native payloads."""
    marker = _marker(conn)
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM session_message_attempts WHERE message_id={marker}",
        (message_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT attempt_id,target_session_id,broker_session_id,attempt_kind,"
        "adapter_revision,started_at,completed_at,result_code,evidence "
        f"FROM session_message_attempts WHERE message_id={marker} "
        "ORDER BY started_at,attempt_id LIMIT " + str(ATTEMPT_READ_LIMIT),
        (message_id,),
    ).fetchall()
    attempts = [
        {
            "attempt_id": str(row[0]),
            "target_session_id": str(row[1]),
            "broker_session_id": str(row[2]) if row[2] is not None else None,
            "attempt_kind": str(row[3]),
            "adapter_revision": str(row[4]) if row[4] is not None else None,
            "started_at": str(row[5]),
            "completed_at": str(row[6]) if row[6] is not None else None,
            "result_code": str(row[7]) if row[7] is not None else None,
            "evidence": _evidence(row[8]),
        }
        for row in rows
    ]
    total = int(total_row[0]) if total_row is not None else 0
    return {
        "attempts": attempts,
        "attempt_count": total,
        "attempts_truncated": total > len(attempts),
    }


__all__ = ["ATTEMPT_READ_LIMIT", "message_attempt_evidence"]

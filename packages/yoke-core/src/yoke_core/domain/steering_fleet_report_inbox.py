"""This session's injected-but-unacked Fleet inbox for the fleet report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_authorization import (
    SessionMessageError,
    project_policy,
)
from yoke_core.domain.session_message_types import parse_timestamp, row_dict


@dataclass(frozen=True)
class UnackedInjectedMessage:
    """One injected receipt on this session still waiting for acknowledgement."""

    message_id: str
    last_injected_at: str
    age_seconds: int


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _age_label(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def wake_ack_grace_seconds(conn: Any, project_id: int | None) -> int:
    """Org fleet grace, or the closed default when no project is in hand."""
    default = int(FLEET_KEY_SPECS["fleet.wake_ack_grace_seconds"].default)
    if project_id is None:
        return default
    try:
        return int(project_policy(conn, int(project_id)).wake_ack_grace_seconds)
    except (SessionMessageError, TypeError, ValueError):
        return default


def load_unacked_injected(
    conn: Any,
    *,
    session_id: str,
    now: str,
    grace_seconds: int,
) -> tuple[UnackedInjectedMessage, ...]:
    """Injected receipts for *session_id* past the acknowledgement grace."""
    moment = parse_timestamp(now) or datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT r.message_id, r.last_injected_at "
        "FROM session_message_recipients r "
        f"WHERE r.session_id={_p(conn)} AND r.state='injected' "
        "AND r.acknowledged_at IS NULL AND r.last_injected_at IS NOT NULL "
        "ORDER BY r.last_injected_at ASC",
        (session_id,),
    ).fetchall()
    found: list[UnackedInjectedMessage] = []
    for raw in rows:
        row = row_dict(raw) if not isinstance(raw, dict) else raw
        injected_at = parse_timestamp(row.get("last_injected_at"))
        if injected_at is None:
            continue
        age = int((moment - injected_at).total_seconds())
        if age < int(grace_seconds):
            continue
        found.append(
            UnackedInjectedMessage(
                message_id=str(row["message_id"]),
                last_injected_at=str(row.get("last_injected_at") or ""),
                age_seconds=age,
            )
        )
    return tuple(found)


def unacked_section_lines(rows: tuple[UnackedInjectedMessage, ...]) -> list[str]:
    """Render the this-session unacked inbox, or nothing when empty."""
    if not rows:
        return []
    lines = [
        "unacked injected (this session) — already shown, still awaiting ack:"
    ]
    for row in rows:
        lines.append(
            f"  {row.message_id}  injected {_age_label(row.age_seconds)} ago  "
            f"yoke messages acknowledge {row.message_id}"
        )
    return lines


__all__ = [
    "UnackedInjectedMessage",
    "load_unacked_injected",
    "unacked_section_lines",
    "wake_ack_grace_seconds",
]

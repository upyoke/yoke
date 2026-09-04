"""Additive convergence for session-control tables born on older schemas."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.launch_origin import ORIGIN_COLUMN_DDL
from yoke_contracts.session_control.sender_surface import SENDER_SURFACES
from yoke_core.domain.actor_message_recipient_schema import (
    converge_role_addressed_recipients,
)
from yoke_core.domain.schema_common import _column_exists


SENDER_SURFACE_VALUES_SQL = ",".join(f"'{value}'" for value in SENDER_SURFACES)


def converge_session_control_schema(conn: Any) -> None:
    """Add columns that ``CREATE TABLE IF NOT EXISTS`` cannot converge."""
    if not _column_exists(conn, "session_launch_attempts", "batch_id"):
        conn.execute("ALTER TABLE session_launch_attempts ADD COLUMN batch_id TEXT")
    if not _column_exists(conn, "session_launches", "origin"):
        conn.execute(
            f"ALTER TABLE session_launches ADD COLUMN origin {ORIGIN_COLUMN_DDL}"
        )
    if not _column_exists(conn, "session_launches", "session_name"):
        conn.execute("ALTER TABLE session_launches ADD COLUMN session_name TEXT")
    for name, column_type in (
        ("requested_reasoning_effort", "TEXT"),
        ("requested_context_window_tokens", "INTEGER"),
        ("native_launch_pid", "INTEGER"),
        ("native_launch_phase", "TEXT"),
        ("native_launch_observed_at", "TEXT"),
        ("spawn_duration_ms", "INTEGER"),
        ("spawn_hold_reason", "TEXT"),
        ("placement_reason", "TEXT"),
        ("resolved_model", "TEXT"),
    ):
        if not _column_exists(conn, "session_launches", name):
            conn.execute(
                f"ALTER TABLE session_launches ADD COLUMN {name} {column_type}"
            )
    for name in (
        "surface_plan_limits",
        "machine_capacity",
        "preferred_session_models",
        "relay_health",
    ):
        if not _column_exists(conn, "session_relays", name):
            conn.execute(f"ALTER TABLE session_relays ADD COLUMN {name} TEXT")
    if not _column_exists(conn, "session_message_recipients", "wake_escalation"):
        conn.execute(
            "ALTER TABLE session_message_recipients ADD COLUMN wake_escalation TEXT"
        )
    if not _column_exists(conn, "session_messages", "sender_surface"):
        conn.execute(
            "ALTER TABLE session_messages ADD COLUMN sender_surface TEXT "
            f"CHECK(sender_surface IN ({SENDER_SURFACE_VALUES_SQL}))"
        )
    converge_role_addressed_recipients(conn)


__all__ = ["SENDER_SURFACE_VALUES_SQL", "converge_session_control_schema"]

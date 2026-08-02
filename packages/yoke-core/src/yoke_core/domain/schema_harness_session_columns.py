"""Idempotent column additions for harness-session attribution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists


def apply_harness_session_columns(conn: Any) -> None:
    """Add the independently evolving harness-session columns."""
    for column, ddl in (
        ("current_item_id", "TEXT DEFAULT NULL"),
        ("current_item_set_at", "TEXT DEFAULT NULL"),
        ("recent_item_id", "TEXT DEFAULT NULL"),
        ("recent_item_status", "TEXT DEFAULT NULL"),
        ("recent_item_recorded_at", "TEXT DEFAULT NULL"),
        ("actor_id", "INTEGER DEFAULT NULL"),
        ("last_seen_main_sha", "TEXT DEFAULT NULL"),
        ("last_drift_check_at", "TEXT DEFAULT NULL"),
        ("executor_display_name", "TEXT DEFAULT NULL"),
        ("last_tool_call_at", "TEXT DEFAULT NULL"),
        ("tool_call_count", "INTEGER NOT NULL DEFAULT 0"),
        ("episode_started_at", "TEXT DEFAULT NULL"),
        ("pending_resume_notice", "TEXT DEFAULT NULL"),
        ("last_chain_step", "INTEGER DEFAULT NULL"),
        ("last_checkpoint_at", "TEXT DEFAULT NULL"),
    ):
        _add_column_if_not_exists(conn, "harness_sessions", column, ddl)
    conn.commit()

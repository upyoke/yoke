"""Idempotent column additions for harness-session attribution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.session_turn_posture import (
    TURN_POSTURE_AT_COLUMN_DDL,
    TURN_POSTURE_COLUMN_DDL,
)


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
        ("executor_surface", "TEXT DEFAULT NULL"),
        ("presentation_surface", "TEXT DEFAULT NULL"),
        ("presentation_state", "TEXT DEFAULT NULL"),
        ("presentation_mode", "TEXT DEFAULT NULL"),
        ("presentation_source", "TEXT DEFAULT NULL"),
        ("presentation_observed_at", "TEXT DEFAULT NULL"),
        ("executor_version", "TEXT DEFAULT NULL"),
        ("machine_id", "TEXT DEFAULT NULL"),
        ("last_tool_call_at", "TEXT DEFAULT NULL"),
        ("tool_call_count", "INTEGER NOT NULL DEFAULT 0"),
        ("episode_started_at", "TEXT DEFAULT NULL"),
        ("pending_resume_notice", "TEXT DEFAULT NULL"),
        ("last_chain_step", "INTEGER DEFAULT NULL"),
        ("last_checkpoint_at", "TEXT DEFAULT NULL"),
        ("turn_posture", TURN_POSTURE_COLUMN_DDL),
        ("turn_posture_at", TURN_POSTURE_AT_COLUMN_DDL),
        ("native_thread_id", "TEXT DEFAULT NULL"),
        ("terminated_at", "TEXT DEFAULT NULL"),
        ("terminated_by_actor_id", "INTEGER DEFAULT NULL"),
        ("terminated_by_session_id", "TEXT DEFAULT NULL"),
        ("termination_reason", "TEXT DEFAULT NULL"),
        ("parked_reason", "TEXT DEFAULT NULL"),
        ("keepalive_until", "TEXT DEFAULT NULL"),
        ("keepalive_reason", "TEXT DEFAULT NULL"),
        ("last_steering_report_at", "TEXT DEFAULT NULL"),
        ("last_steering_report_fingerprint", "TEXT DEFAULT NULL"),
        # The ask, stamped once: from the session's own environment at
        # registration, and from the launch record at launch binding.
        ("requested_model", "TEXT DEFAULT NULL"),
        ("requested_reasoning_effort", "TEXT DEFAULT NULL"),
        ("requested_context_window_tokens", "INTEGER DEFAULT NULL"),
        # Provider-attested served truth; NULL means not attested.
        ("reasoning_effort", "TEXT DEFAULT NULL"),
        ("context_window_tokens", "INTEGER DEFAULT NULL"),
    ):
        _add_column_if_not_exists(conn, "harness_sessions", column, ddl)
    conn.commit()

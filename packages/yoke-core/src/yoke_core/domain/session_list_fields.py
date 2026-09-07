"""Stable output fields for the session roster read model, and their
derivations that are more than a column read."""

from typing import Any, Mapping

from yoke_contracts.session_usage_display import (
    USAGE_PROJECTION_FIELDS,
    usage_projection,
)

SESSION_LIST_FIELDS = (
    "session_id",
    "liveness",
    "ended_cause",
    "activity_at",
    "execution_lane",
    "lane_label",
    "lane_glyph",
    "mode",
    "quiet_reason",
    "keepalive_until",
    "keepalive_reason",
    "actor_id",
    "actor_kind",
    "actor_label",
    "project_id",
    "project",
    "executor",
    "executor_surface",
    "executor_mark",
    "executor_class_name",
    "presentation_surface",
    "presentation_state",
    "presentation_mode",
    "presentation_source",
    "presentation_observed_at",
    "model",
    "reasoning_effort",
    "context_window_tokens",
    *USAGE_PROJECTION_FIELDS,
    "workspace",
    "offered_at",
    "native_process",
    "ended_at",
    "terminated_at",
    "terminated_by_actor_id",
    "terminated_by_session_id",
    "termination_reason",
    "current_item",
    "current_item_project_id",
    "current_item_project_sequence",
    "current_item_title",
    "current_item_status",
    "current_item_workflow_id",
    "current_item_workflow_version_id",
    "work_role",
    "owns_current_item",
    "current_item_holder_session_id",
    "claim_started_at",
    "claims",
    "holdings",
    "claimed_blitz_worktree_ids",
)


def usage_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Derive this row's consumption fields from its stored reading.

    The roster ships figures rather than the stored document so pricing
    happens once, here, instead of separately in every reader.
    """
    return usage_projection(row.get("usage_totals"))


__all__ = ["SESSION_LIST_FIELDS", "usage_fields"]

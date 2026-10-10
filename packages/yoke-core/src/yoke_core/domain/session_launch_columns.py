"""Stored launch columns and their native instant update boundary."""

LAUNCH_COLUMNS = (
    "launch_id, requester_actor_id, requester_session_id, project_id, "
    "requested_surface, selected_surface, requested_machine_id, requested_model, "
    "requested_reasoning_effort, requested_context_window_tokens, "
    "presentation_preference, session_name, allow_surface_fallback, message_id, "
    "idempotency_key, state, assigned_relay_id, assigned_machine_id, "
    "native_session_id, attestation_hash, attestation_consumed_at, "
    "registered_session_id, deadline_at, created_at, assigned_at, launching_at, "
    "awaiting_registration_at, completed_at, result_code, result_evidence, origin, "
    "native_launch_pid, native_launch_phase, native_launch_observed_at, "
    "spawn_duration_ms, spawn_hold_reason, placement_reason, resolved_model, "
    "resolved_reasoning_effort, resolved_context_window_tokens, requested_level, "
    "level_placement"
)
MUTABLE_LAUNCH_COLUMNS = frozenset(
    {
        "state",
        "selected_surface",
        "assigned_relay_id",
        "assigned_machine_id",
        "native_session_id",
        "attestation_hash",
        "attestation_consumed_at",
        "registered_session_id",
        "deadline_at",
        "assigned_at",
        "launching_at",
        "awaiting_registration_at",
        "completed_at",
        "result_code",
        "result_evidence",
        "native_launch_pid",
        "native_launch_phase",
        "native_launch_observed_at",
        "spawn_duration_ms",
        "spawn_hold_reason",
        "placement_reason",
        "resolved_model",
        "resolved_reasoning_effort",
        "resolved_context_window_tokens",
        "level_placement",
    }
)


INSTANT_LAUNCH_COLUMNS = frozenset(
    (
        "attestation_consumed_at",
        "deadline_at",
        "created_at",
        "assigned_at",
        "launching_at",
        "awaiting_registration_at",
        "completed_at",
        "native_launch_observed_at",
    )
)

"""Function registration for the narrow release-pin mutation."""

from __future__ import annotations

from yoke_core.domain.handlers import release_pin_record


def register(registry) -> None:
    registry.register(
        "release_pin.record",
        release_pin_record.handle_release_pin_record,
        release_pin_record.ReleasePinRecordRequest,
        release_pin_record.ReleasePinRecordResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.release_pin_record",
        target_kinds=["global"],
        side_effects=["environments_settings_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "configured_environment_only",
            "configured_scalar_path_only",
            "project_environment_match",
            "value_compare_and_swap",
            "idempotent_same_pin",
            "changed_paths_only_receipt",
        ],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]

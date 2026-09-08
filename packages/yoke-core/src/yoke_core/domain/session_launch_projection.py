"""Operator-safe launch records for registered-function responses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_core.domain import json_helper
from yoke_core.domain.session_launch_types import LaunchRecord
from yoke_core.domain.session_launch_visibility import launch_visibility


_PUBLIC_FIELDS = (
    "launch_id",
    "project_id",
    "requested_surface",
    "selected_surface",
    "requested_machine_id",
    "requested_model",
    "requested_reasoning_effort",
    "requested_context_window_tokens",
    "presentation_preference",
    "session_name",
    "allow_surface_fallback",
    "state",
    "assigned_relay_id",
    "assigned_machine_id",
    "placement_reason",
    "resolved_model",
    "resolved_reasoning_effort",
    "resolved_context_window_tokens",
    "native_session_id",
    "attestation_consumed_at",
    "registered_session_id",
    "deadline_at",
    "created_at",
    "assigned_at",
    "launching_at",
    "awaiting_registration_at",
    "completed_at",
    "result_code",
    "origin",
    "native_launch_pid",
    "native_launch_phase",
    "native_launch_observed_at",
    "spawn_duration_ms",
    "spawn_hold_reason",
)


def _safe_result_evidence(value: Any) -> dict[str, str | int]:
    if isinstance(value, Mapping):
        decoded = value
    else:
        try:
            decoded = json_helper.loads_text(str(value))
        except (TypeError, ValueError):
            decoded = None
    return redacted_evidence_document(decoded)


def public_launch_record(launch: LaunchRecord) -> dict[str, Any]:
    """Project one launch without request identity, secrets, or native payloads."""
    result = {field: getattr(launch, field) for field in _PUBLIC_FIELDS}
    result.update(
        launch_visibility(
            state=launch.state,
            result_code=launch.result_code,
            native_session_id=launch.native_session_id,
            registered_session_id=launch.registered_session_id,
        )
    )
    result["result_evidence"] = _safe_result_evidence(launch.result_evidence)
    return result


#: What a list row shows before it is expanded. Everything a reader needs to
#: recognise a launch and decide whether to open it; the rich record behind
#: `public_launch_record` is fetched only when one is expanded.
_COMPACT_FIELDS = (
    "launch_id",
    "project_id",
    "state",
    "result_code",
    "requested_surface",
    "selected_surface",
    "requested_machine_id",
    "assigned_machine_id",
    "resolved_model",
    "resolved_reasoning_effort",
    "resolved_context_window_tokens",
    "created_at",
    "completed_at",
    "registered_session_id",
)


def compact_launch_record(
    launch: LaunchRecord, project: str | None = None
) -> dict[str, Any]:
    """Project one launch as a list row, labelled with its project."""
    row = {field: getattr(launch, field) for field in _COMPACT_FIELDS}
    row["project"] = project
    return row


def compact_launch_records(
    launches: Iterable[LaunchRecord], project: str | None = None
) -> list[dict[str, Any]]:
    return [compact_launch_record(launch, project) for launch in launches]


__all__ = [
    "compact_launch_record",
    "compact_launch_records",
    "public_launch_record",
]

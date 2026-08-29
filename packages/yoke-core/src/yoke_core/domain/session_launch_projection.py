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
    "presentation_preference",
    "session_name",
    "allow_surface_fallback",
    "state",
    "assigned_relay_id",
    "assigned_machine_id",
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


def public_launch_records(launches: Iterable[LaunchRecord]) -> list[dict[str, Any]]:
    return [public_launch_record(launch) for launch in launches]


__all__ = ["public_launch_record", "public_launch_records"]

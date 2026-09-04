"""Shape checks for one relay heartbeat before anything about it is stored."""

from __future__ import annotations

import uuid

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.machine_config.machine_capacity import sanitize_machine_capacity
from yoke_contracts.session_control.plan_limits import sanitize_plan_limits
from yoke_contracts.session_control.relay_health import sanitize_relay_health
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
    advertised_session_models,
    advertised_session_reasoning_efforts,
)


def validate_heartbeat(heartbeat: RelayHeartbeat) -> RelayHeartbeat:
    if not heartbeat.relay_id.strip() or len(heartbeat.relay_id) > 128:
        raise SessionRelayError("relay_id_invalid", "relay_id must be 1-128 characters")
    try:
        machine_id = str(uuid.UUID(heartbeat.machine_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SessionRelayError(
            "machine_id_invalid", "machine_id must be a canonical UUID"
        ) from exc
    if machine_id != heartbeat.machine_id:
        raise SessionRelayError(
            "machine_id_invalid", "machine_id must be a canonical UUID"
        )
    actor_id = int(heartbeat.actor_id)
    if actor_id <= 0:
        raise SessionRelayError(
            "relay_actor_invalid", "relay actor must be a positive integer"
        )
    unknown = sorted(set(heartbeat.surface_versions) - set(KNOWN_SURFACE_LABELS))
    if unknown:
        raise SessionRelayError(
            "surface_invalid", f"unknown relay surfaces: {', '.join(unknown)}"
        )
    relay_version = str(heartbeat.relay_version).strip()
    if not relay_version or len(relay_version) > 128:
        raise SessionRelayError(
            "relay_version_invalid", "relay version must be 1-128 characters"
        )
    for surface, version in heartbeat.surface_versions.items():
        if not str(version).strip() or len(str(version)) > 128:
            raise SessionRelayError(
                "surface_version_invalid", f"{surface} version must be 1-128 characters"
            )
    project_ids = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if any(value <= 0 for value in project_ids):
        raise SessionRelayError(
            "project_id_invalid", "relay project ids must be positive integers"
        )
    hostname = heartbeat.hostname.strip()
    if not hostname or len(hostname) > 255:
        raise SessionRelayError(
            "hostname_invalid", "relay hostname must be 1-255 characters"
        )
    return RelayHeartbeat(
        relay_id=heartbeat.relay_id.strip(),
        actor_id=actor_id,
        machine_id=machine_id,
        hostname=hostname,
        relay_version=relay_version,
        surface_versions={
            surface: str(heartbeat.surface_versions[surface]).strip()
            for surface in sorted(heartbeat.surface_versions)
        },
        project_ids=project_ids,
        surface_plan_limits=sanitize_plan_limits(heartbeat.surface_plan_limits),
        preferred_session_models=advertised_session_models(
            heartbeat.preferred_session_models
        ),
        preferred_session_reasoning_efforts=advertised_session_reasoning_efforts(
            heartbeat.preferred_session_reasoning_efforts
        ),
        machine_capacity=sanitize_machine_capacity(heartbeat.machine_capacity),
        relay_health=sanitize_relay_health(heartbeat.relay_health),
    )


__all__ = ["validate_heartbeat"]

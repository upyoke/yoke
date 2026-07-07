"""Per-capability validators for ``project_capabilities.settings``."""

from __future__ import annotations


def canonicalize_capability_settings(cap_type: str, raw_json: str) -> str:
    """Validate and canonicalize settings JSON for typed capabilities."""
    if cap_type == "migration_model":
        from yoke_core.domain.migration_model_capability import validate_json_string
        return validate_json_string(raw_json)

    from yoke_core.domain.github_actions_runner_fleet_capability import (
        CAPABILITY_TYPE as RUNNER_FLEET_CAPABILITY_TYPE,
    )
    if cap_type == RUNNER_FLEET_CAPABILITY_TYPE:
        from yoke_core.domain.github_actions_runner_fleet_capability import (
            validate_json_string,
        )
        return validate_json_string(raw_json)
    return raw_json


__all__ = ["canonicalize_capability_settings"]

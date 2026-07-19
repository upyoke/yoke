"""Per-capability validators for ``project_capabilities.settings``."""

from __future__ import annotations

from yoke_core.domain import json_helper


def canonicalize_capability_settings(cap_type: str, raw_json: str) -> str:
    """Validate and canonicalize settings JSON for typed capabilities."""
    if cap_type == "migration_model":
        from yoke_core.domain.migration_model_capability import validate_json_string

        return validate_json_string(raw_json)

    if cap_type == "pulumi-state":
        from yoke_core.domain.pulumi_state_capability import validate_json_string

        return validate_json_string(raw_json)

    if cap_type == "ephemeral-env":
        from yoke_core.domain.ephemeral_substrate import (
            ephemeral_policy_from_capability,
        )

        payload = json_helper.loads_text(raw_json)
        if not isinstance(payload, dict):
            raise ValueError("ephemeral-env settings must be a JSON object")
        ephemeral_policy_from_capability("project", payload, deploy_namespace="project")
        return json_helper.dumps_compact(payload)

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

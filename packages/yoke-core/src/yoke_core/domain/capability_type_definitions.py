"""Definition-owned presentation and read-model policy for capability types."""

from __future__ import annotations

from typing import Any

from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE
from yoke_contracts.project_contract.project_keys import (
    PROJECT_POLICY_CAPABILITY,
    SESSION_ROUTING_CAPABILITY,
)
from yoke_core.domain.migration_model_capability_validation import (
    CAPABILITY_TYPE as MIGRATION_MODEL_CAPABILITY_TYPE,
)
from yoke_core.domain.migration_model_fleet import (
    CAPABILITY_TYPE as MIGRATION_FLEET_CAPABILITY_TYPE,
)

KIND_DECLARED_MODEL = "declared_model"
KIND_PROVIDER_ACCESS = "provider_access"


_DEFAULT_DEFINITION: dict[str, Any] = {
    "display_label": "",
    "display_type": "",
    "display_order": 1000,
    "detail_view": "",
    "kind": KIND_PROVIDER_ACCESS,
    "settings_summary": "generic",
    "state_model": "verified",
    "verification_model": "capability",
    "used_by": "",
}

CAPABILITY_TYPE_DEFINITIONS: dict[str, dict[str, Any]] = {
    PROJECT_POLICY_CAPABILITY: {
        "display_label": "Project policy",
        "display_order": 10,
        "kind": KIND_DECLARED_MODEL,
        "used_by": "all workflows",
    },
    SESSION_ROUTING_CAPABILITY: {
        "display_label": "Session routing",
        "display_order": 20,
        "kind": KIND_DECLARED_MODEL,
        "used_by": "session registration",
    },
    MIGRATION_MODEL_CAPABILITY_TYPE: {
        "display_label": "Migration model",
        "display_order": 30,
        "kind": KIND_DECLARED_MODEL,
        "settings_summary": "migration_model",
        "used_by": "all workflows",
    },
    MIGRATION_FLEET_CAPABILITY_TYPE: {
        "display_label": "Migration fleet",
        "display_order": 31,
        "kind": KIND_DECLARED_MODEL,
        "used_by": "Delivery · release fleet rehearsal",
    },
    GITHUB_CAPABILITY_TYPE: {
        "display_label": "GitHub",
        "display_order": 40,
        "settings_summary": "github",
        "verification_model": "repo_binding",
        "used_by": "GitHub · delivery",
    },
    "azure-admin": {
        "display_label": "Azure admin",
        "display_order": 51,
        "used_by": "Test Machine power",
    },
    "aws-admin": {
        "display_label": "AWS admin",
        "display_order": 50,
        "used_by": "Delivery · Infrastructure",
    },
    "browser-control": {
        "display_label": "Browser control",
        "display_order": 60,
    },

}


def capability_type_definition(capability_type: str) -> dict[str, Any]:
    """Return a complete caller-owned definition for one stored type."""
    definition = CAPABILITY_TYPE_DEFINITIONS.get(capability_type)
    result = dict(_DEFAULT_DEFINITION)
    result.update(definition or {})
    result["display_label"] = result["display_label"] or capability_type.replace(
        "-", " "
    )
    result["display_type"] = result["display_type"] or capability_type
    return result


__all__ = [
    "CAPABILITY_TYPE_DEFINITIONS",
    "KIND_DECLARED_MODEL",
    "KIND_PROVIDER_ACCESS",
    "capability_type_definition",
]

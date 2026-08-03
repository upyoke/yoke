"""Canonical current definitions and immutable history for built-in workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from yoke_core.domain.builtin_delivery_workflow_definitions import (
    EPIC_WORKFLOW_DEFINITION,
    ISSUE_WORKFLOW_DEFINITION,
)
from yoke_core.domain.builtin_delivery_workflow_version_history import (
    EPIC_WORKFLOW_VERSION_ONE,
    ISSUE_WORKFLOW_VERSION_ONE,
)
from yoke_core.domain.builtin_direct_workflow_definitions import (
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
)
from yoke_core.domain.builtin_direct_workflow_version_history import (
    BLITZ_WORKFLOW_VERSION_ONE,
    DASH_WORKFLOW_VERSION_ONE,
)
from yoke_core.domain.workflow_definition_builders import (
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
    ENTRY_SURFACE_IDS,
    REGISTERED_WORKFLOW_SKILL_IDS,
    WORKFLOW_DEFINITION_SCHEMA_VERSION,
)

BUILTIN_WORKFLOW_IDS = ("issue", "epic", "blitz", "dash")

_BUILTIN_WORKFLOW_DEFINITIONS = (
    ISSUE_WORKFLOW_DEFINITION,
    EPIC_WORKFLOW_DEFINITION,
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
)


def _version_two_fixture(current: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruct the exact schema-v1 definition published as version 2."""
    fixture = deepcopy(current)
    fixture["version"] = 2
    definition = fixture["definition"]
    definition["schema_version"] = 1
    policies = definition["policies"]
    policies.pop("file_budget")
    policies.pop("path_survey", None)
    policies["item_posture_allowlist"] = [
        value
        for value in policies["item_posture_allowlist"]
        if value not in {"file_budget", "path_survey"}
    ]
    return fixture


_BUILTIN_WORKFLOW_VERSION_HISTORY = (
    ISSUE_WORKFLOW_VERSION_ONE,
    EPIC_WORKFLOW_VERSION_ONE,
    BLITZ_WORKFLOW_VERSION_ONE,
    DASH_WORKFLOW_VERSION_ONE,
    *tuple(
        _version_two_fixture(fixture)
        for fixture in _BUILTIN_WORKFLOW_DEFINITIONS
    ),
)


def builtin_workflow_definitions() -> list[Dict[str, Any]]:
    """Return caller-owned copies of the four current definitions."""
    return deepcopy(list(_BUILTIN_WORKFLOW_DEFINITIONS))


def builtin_workflow_definition(workflow_id: str) -> Dict[str, Any]:
    """Return one caller-owned current definition by stable workflow id."""
    for fixture in _BUILTIN_WORKFLOW_DEFINITIONS:
        if fixture["workflow"]["id"] == workflow_id:
            return deepcopy(fixture)
    raise KeyError(workflow_id)


def builtin_workflow_version_history() -> list[Dict[str, Any]]:
    """Return caller-owned copies of fixed previously published versions."""
    return deepcopy(list(_BUILTIN_WORKFLOW_VERSION_HISTORY))


__all__ = [
    "BUILTIN_WORKFLOW_IDS",
    "BUILTIN_WORKFLOW_PREFERRED_VERSION",
    "ENTRY_SURFACE_IDS",
    "REGISTERED_WORKFLOW_SKILL_IDS",
    "WORKFLOW_DEFINITION_SCHEMA_VERSION",
    "builtin_workflow_definition",
    "builtin_workflow_definitions",
    "builtin_workflow_version_history",
]

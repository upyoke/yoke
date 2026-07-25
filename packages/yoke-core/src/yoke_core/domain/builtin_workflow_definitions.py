"""Canonical first published definitions for Yoke's built-in workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from yoke_core.domain.builtin_delivery_workflow_definitions import (
    EPIC_WORKFLOW_DEFINITION,
    ISSUE_WORKFLOW_DEFINITION,
)
from yoke_core.domain.builtin_direct_workflow_definitions import (
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
)
from yoke_core.domain.workflow_definition_builders import (
    ENTRY_SURFACE_IDS,
    REGISTERED_WORKFLOW_EXECUTOR_IDS,
    WORKFLOW_DEFINITION_SCHEMA_VERSION,
)

BUILTIN_WORKFLOW_IDS = ("issue", "epic", "blitz", "dash")

_BUILTIN_WORKFLOW_DEFINITIONS = (
    ISSUE_WORKFLOW_DEFINITION,
    EPIC_WORKFLOW_DEFINITION,
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
)


def builtin_workflow_definitions() -> list[Dict[str, Any]]:
    """Return caller-owned copies of all first published definitions."""
    return deepcopy(list(_BUILTIN_WORKFLOW_DEFINITIONS))


def builtin_workflow_definition(workflow_id: str) -> Dict[str, Any]:
    """Return one caller-owned first definition by stable workflow id."""
    for fixture in _BUILTIN_WORKFLOW_DEFINITIONS:
        if fixture["workflow"]["id"] == workflow_id:
            return deepcopy(fixture)
    raise KeyError(workflow_id)


__all__ = [
    "BUILTIN_WORKFLOW_IDS",
    "ENTRY_SURFACE_IDS",
    "REGISTERED_WORKFLOW_EXECUTOR_IDS",
    "WORKFLOW_DEFINITION_SCHEMA_VERSION",
    "builtin_workflow_definition",
    "builtin_workflow_definitions",
]

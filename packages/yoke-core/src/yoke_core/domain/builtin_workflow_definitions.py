"""Canonical current definitions and immutable history for built-in workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from yoke_core.domain.builtin_delivery_workflow_definitions import (
    EPIC_WORKFLOW_DEFINITION,
    ISSUE_WORKFLOW_DEFINITION,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.builtin_direct_workflow_definitions import (
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
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
    """Return caller-owned copies of every published generation.

    Sourced from the canon on disk. It was previously rebuilt by subtracting
    remembered fields from the current definitions, which meant any change to a
    current definition silently rewrote history and refused the next boot.
    """
    return [
        {
            "workflow": {"id": generation.workflow_id},
            "version": generation.canon_version,
            "definition": deepcopy(generation.definition),
        }
        for generation in canon_generations()
    ]


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

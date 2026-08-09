"""Canonical current definitions and immutable history for built-in workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from yoke_core.domain.builtin_delivery_workflow_definitions import (
    EPIC_WORKFLOW_DEFINITION,
    ISSUE_WORKFLOW_DEFINITION,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations, recognize
from yoke_core.domain.builtin_direct_workflow_definitions import (
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
)
from yoke_core.domain.workflow_definition_builders import (
    ENTRY_SURFACE_IDS,
    REGISTERED_WORKFLOW_SKILL_IDS,
    TASK_PRODUCING_PLANNING_SKILL_IDS,
    WORKFLOW_DEFINITION_SCHEMA_VERSION,
)
from yoke_core.domain.workflow_definition_codec import definition_digest

BUILTIN_WORKFLOW_IDS = ("issue", "epic", "blitz", "dash")

_BUILTIN_WORKFLOW_DEFINITIONS = (
    ISSUE_WORKFLOW_DEFINITION,
    EPIC_WORKFLOW_DEFINITION,
    BLITZ_WORKFLOW_DEFINITION,
    DASH_WORKFLOW_DEFINITION,
)


def _with_canon_version(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp which published generation this current definition is.

    A definition carries no version of its own -- a version is a position in
    some universe's sequence. What a current definition does have is a place in
    Yoke's published canon, and that is a fact about the content, so it is
    resolved by digest rather than declared by hand. Declaring it by hand is
    how the code came to claim one global version number for four workflows
    that had published different numbers of times.
    """
    copied = deepcopy(fixture)
    generation = recognize(
        str(copied["workflow"]["id"]), definition_digest(copied["definition"])
    )
    copied["canon_version"] = (
        generation.canon_version if generation is not None else None
    )
    return copied


def builtin_workflow_definitions() -> list[Dict[str, Any]]:
    """Return caller-owned copies of the four current definitions."""
    return [_with_canon_version(fixture) for fixture in _BUILTIN_WORKFLOW_DEFINITIONS]


def builtin_workflow_definition(workflow_id: str) -> Dict[str, Any]:
    """Return one caller-owned current definition by stable workflow id."""
    for fixture in _BUILTIN_WORKFLOW_DEFINITIONS:
        if fixture["workflow"]["id"] == workflow_id:
            return _with_canon_version(fixture)
    raise KeyError(workflow_id)


def builtin_workflow_version_history() -> list[Dict[str, Any]]:
    """Return caller-owned copies of every published generation.

    Sourced from the canon on disk. It was previously rebuilt by subtracting
    remembered fields from the current definitions, which meant any change to a
    current definition silently rewrote history and refused the next boot.
    """
    return [
        {
            # The workflow block is identity (name, description, source), not
            # version content, so it comes from the current definition rather
            # than being frozen per generation.
            "workflow": deepcopy(
                builtin_workflow_definition(generation.workflow_id)["workflow"]
            ),
            "canon_version": generation.canon_version,
            "definition": deepcopy(generation.definition),
        }
        for generation in canon_generations()
    ]


__all__ = [
    "BUILTIN_WORKFLOW_IDS",
    "ENTRY_SURFACE_IDS",
    "REGISTERED_WORKFLOW_SKILL_IDS",
    "TASK_PRODUCING_PLANNING_SKILL_IDS",
    "WORKFLOW_DEFINITION_SCHEMA_VERSION",
    "builtin_workflow_definition",
    "builtin_workflow_definitions",
    "builtin_workflow_version_history",
]

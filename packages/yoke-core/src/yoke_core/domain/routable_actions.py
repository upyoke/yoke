"""The one catalog of actions a lane may be allowed to run.

A lane's allowlist, the gate that reads it, the settings validator that
accepts it, and the Project settings summary that displays it all need the
same answer to "which actions exist, and what is each one called?". Kept in
one place because the alternative — a backend list of tokens beside a
frontend list of labels — drifts the moment either side gains an action,
and the drift shows up as a lane that silently allows a path the operator
cannot see, or a summary naming an action nothing dispatches.

Membership is derived rather than declared: an action is routable exactly
when something can dispatch a session onto it. That is the lifecycle paths
the scheduler resolves work onto, the process paths the process-offer gate
recognises, and the standing steering path a session runs against a
strategy document. Installed skills are deliberately not the source — most
of them are steps inside one of these paths, not destinations a lane can be
routed to.

Presentation is declared here, and the two halves are checked against each
other on first use: a dispatch path with no presentation entry, or a
presentation entry nothing dispatches, raises instead of rendering a
half-answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Tuple

from yoke_core.domain.sessions_analytics_core import lifecycle_dispatch_paths
from yoke_core.domain.work_processes import process_dispatch_paths


STEERING_ACTION = "steer"
"""The standing steering path, dispatched from a strategy document rather
than from a work item, so neither dispatch map above carries it."""


@dataclass(frozen=True)
class RoutableAction:
    """One action a lane allowlist may contain, with its operator wording."""

    id: str
    label: str
    description: str


class RoutableActionCatalogError(RuntimeError):
    """Raised when dispatch support and catalog presentation disagree."""


_PRESENTATION: Dict[str, Tuple[str, str]] = {
    "shepherd": ("Shepherd", "Plan work through its quality gates."),
    "advance": ("Advance", "Move work to its next lifecycle stage."),
    "conduct": ("Conduct", "Execute an epic's implementation tasks."),
    "dash": ("Dash", "Complete a small, instruction-sized change."),
    "blitz": ("Blitz", "Execute substantial work from a standing plan."),
    "refine": ("Refine", "Improve a work item's specification."),
    "polish": ("Polish", "Review and finish implementation."),
    "usher": ("Usher", "Merge and deploy completed work."),
    "strategize": ("Strategize", "Review and shape project strategy."),
    "feed": ("Feed", "Refresh the frontier and create work from strategy."),
    STEERING_ACTION: (
        "Steer",
        "Continuously steer work against a strategy document.",
    ),
    "doctor": ("Doctor", "Check project and delivery-system health."),
}


def dispatch_supported_action_ids() -> frozenset[str]:
    """Return every action id something can currently dispatch a session onto."""
    return frozenset(
        {*lifecycle_dispatch_paths(), *process_dispatch_paths(), STEERING_ACTION}
    )


@lru_cache(maxsize=1)
def routable_actions() -> Tuple[RoutableAction, ...]:
    """Return the catalog in display order, refusing a half-defined action."""
    supported = dispatch_supported_action_ids()
    described = frozenset(_PRESENTATION)
    undescribed = sorted(supported - described)
    if undescribed:
        raise RoutableActionCatalogError(
            "these dispatch paths have no catalog label or description: "
            f"{', '.join(undescribed)}. Add each one to the presentation map "
            "in yoke_core.domain.routable_actions so lane allowlists and the "
            "Project settings summary can name it."
        )
    undispatchable = sorted(described - supported)
    if undispatchable:
        raise RoutableActionCatalogError(
            "these catalog actions are not dispatchable: "
            f"{', '.join(undispatchable)}. Remove each one from the "
            "presentation map in yoke_core.domain.routable_actions, or add "
            "its dispatch route, so a lane cannot allow an action nothing "
            "can run."
        )
    return tuple(
        RoutableAction(id=action_id, label=label, description=description)
        for action_id, (label, description) in _PRESENTATION.items()
    )


def routable_action_ids() -> Tuple[str, ...]:
    """Return catalog action ids in display order."""
    return tuple(action.id for action in routable_actions())


def is_routable_action(action_id: object) -> bool:
    """True when ``action_id`` names a catalog action."""
    return isinstance(action_id, str) and action_id in {
        action.id for action in routable_actions()
    }


def routable_action_catalog_payload() -> list[dict[str, str]]:
    """Return the catalog shaped for a registered read's result payload."""
    return [
        {
            "id": action.id,
            "label": action.label,
            "description": action.description,
        }
        for action in routable_actions()
    ]


__all__ = [
    "STEERING_ACTION",
    "RoutableAction",
    "RoutableActionCatalogError",
    "dispatch_supported_action_ids",
    "is_routable_action",
    "routable_action_catalog_payload",
    "routable_action_ids",
    "routable_actions",
]

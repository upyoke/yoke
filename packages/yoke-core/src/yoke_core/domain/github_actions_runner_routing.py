"""Pure routing-state interpretation for self-hosted Actions runners."""

from __future__ import annotations

from typing import Sequence

from yoke_core.domain import json_helper


def routing_matches(value: str | None, required: Sequence[str]) -> bool:
    """Return whether the repo variable semantically names the required labels."""
    if not value:
        return False
    try:
        parsed = json_helper.loads_text(value)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, list):
        return False
    labels = [item.strip().casefold() for item in parsed if isinstance(item, str)]
    expected = [item.strip().casefold() for item in required]
    return (
        len(labels) == len(parsed) == len(expected)
        and all(labels)
        and set(labels) == set(expected)
    )


def classify_runner_route(
    *,
    matching_count: int,
    online_count: int,
    variable_exists: bool,
    routing_armed: bool,
    routing_enabled: bool,
    capability_configured: bool,
    autoscaled_ephemeral: bool,
) -> tuple[str, str]:
    """Classify online readiness separately from armed scale-to-zero routing."""
    if not capability_configured:
        return (
            "configure_runner_fleet",
            "Configure the github-actions-runner-fleet capability with an "
            "explicit github_capability and github_app, then "
            "apply its runner-fleet Pulumi stack; do not set the routing "
            "variable directly.",
        )
    if not routing_enabled:
        if routing_armed:
            return (
                "apply_runner_fleet",
                "Capability routing_enabled is false but the repository still "
                "routes to the self-hosted labels; apply the runner-fleet "
                "Pulumi stack to remove the managed variable.",
            )
        if variable_exists:
            return (
                "resolve_runner_routing_variable",
                "Capability routing_enabled is false, but a nonmatching "
                "Actions variable already uses the managed name. Review its "
                "ownership: delete or rename it deliberately, or enable "
                "routing and adopt it with a one-time Pulumi import before "
                "applying. This is not a clean hosted-fallback state.",
            )
        return (
            "routing_disabled",
            "Capability routing_enabled is false; workflows use their hosted "
            "fallback and Pulumi omits the self-hosted routing variable.",
        )
    if not routing_armed:
        if variable_exists:
            return (
                "adopt_runner_routing_variable",
                "A nonmatching Actions variable already uses the managed "
                "name. Before applying, adopt it into the "
                "runnerFleetRoutingVariable Pulumi resource with a one-time "
                "pulumi import and review the planned value change.",
            )
        return (
            "apply_runner_fleet",
            "Capability routing_enabled is true but the repository route is "
            "absent or drifted; apply the runner-fleet Pulumi stack to "
            "reconcile it.",
        )
    if online_count > 0:
        return "ready", "Matching online runner exists and routing is armed."
    if matching_count > 0:
        return "start_runner", "Matching runners exist, but none are online."
    if autoscaled_ephemeral:
        return (
            "routing_armed_idle",
            "Runner routing is armed and autoscaling is configured; "
            "no matching runner is currently registered.",
        )
    return "register_runner", "No registered runner has all required labels."


__all__ = ["classify_runner_route", "routing_matches"]

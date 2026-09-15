"""What a run preview's deploy dispatch must carry, and where it lands.

Two trigger models stand a preview up, and a release preview needs the same
two things from either: the frozen candidate to deploy, and a name that does
not move while it is under review. The flow trigger takes both as arguments
and this module has nothing to add. A project whose previews are deployed by
its own GitHub workflow takes them as dispatch inputs instead, and names the
preview after the dispatch identity Yoke already correlates that run by — so
Yoke can compute the origin *before* the deploy reports one, which is what
lets the receipt probe it at all.

Both facts stay project-configured. Which input carries the candidate is the
stage's own ``inputs`` map, the domain the preview is published under is the
project's ``ephemeral-env`` capability, and the derivation from name to slug
is the substrate's parity contract that the ephemeral-environments Pack
workflow mirrors. Nothing here names a project.

What this module owns is the boundary check between the two: that the stage,
as configured, actually carries them. A stage that dispatches the deploy
workflow without the frozen candidate deploys whatever that workflow's own
trigger resolves, and the probe would then read a preview of something else
and call it proof.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    carries_head_sha,
    workflow_dispatch_request_id,
    workflow_inputs,
)
from yoke_core.domain.ephemeral_substrate import (
    TRIGGER_FLOW,
    frozen_preview_slug,
    preview_url,
)

#: The step runner that can carry a frozen candidate and a preview name to a
#: project's own deploy workflow. The other ephemeral step runner deploys a
#: branch from a push and takes neither.
DISPATCHING_STEP_RUNNER = "github-actions-workflow"


def dispatched_preview_origin(
    stage: Mapping[str, Any],
    *,
    project: str,
    run_id: str,
    stage_name: str,
    preview_domain: str,
) -> tuple[str, str]:
    """Return ``(origin, refusal)`` for a workflow-dispatched run preview.

    The origin is where this run's preview will be published, derived from
    the same dispatch identity the dispatcher will send and the same domain
    the project configures. A non-empty refusal means the stage cannot carry
    what a release preview needs, and no deploy should be attempted.
    """
    step_runner = str(stage.get("step_runner") or "")
    if step_runner != DISPATCHING_STEP_RUNNER:
        return "", (
            f"stage {stage_name!r} deploys this run's preview with step "
            f"runner {step_runner!r}, which takes no dispatch inputs, while "
            f"project {project!r} publishes previews from its own deploy "
            f"workflow; a release preview needs the {DISPATCHING_STEP_RUNNER!r} "
            "step runner so the run's frozen candidate and preview name reach "
            "that workflow"
        )
    config = stage.get("config") or {}
    if not isinstance(config, dict):
        config = {}
    correlation = str(config.get("dispatch_correlation_input") or "").strip()
    if correlation != WORKFLOW_DISPATCH_CORRELATION_INPUT:
        return "", (
            f"stage {stage_name!r} declares dispatch correlation input "
            f"{correlation or 'none'!r}, so the deploy workflow receives no "
            "dispatch identity to name this preview after; a release preview "
            "is addressed by that identity, so set "
            f"dispatch_correlation_input: {WORKFLOW_DISPATCH_CORRELATION_INPUT} "
            "on the stage"
        )
    if not carries_head_sha(workflow_inputs(config)):
        return "", (
            f"stage {stage_name!r} passes no input carrying this run's frozen "
            "candidate, so the deploy workflow would resolve its own revision "
            "and the receipt would prove a preview of something else; bind the "
            "workflow's revision input to {head_sha}"
        )
    if not preview_domain:
        return "", (
            f"project {project!r} configures no preview_domain, so the origin "
            "its previews are published at cannot be derived and nothing could "
            "be probed"
        )
    slug = frozen_preview_slug(
        workflow_dispatch_request_id(project, run_id, stage_name)
    )
    return preview_url(slug, preview_domain), ""


def release_preview_origin(
    stage: Mapping[str, Any],
    *,
    project: str,
    run_id: str,
    stage_name: str,
    trigger: str,
    flow_origin: str,
    preview_domain: str,
) -> tuple[str, str]:
    """Return ``(origin, refusal)`` for this run's preview under *trigger*.

    The flow trigger deploys the preview itself and already resolved where
    it lands; any other trigger reaches the project's own deploy workflow,
    which must be handed what it needs.
    """
    if trigger == TRIGGER_FLOW:
        return flow_origin, ""
    return dispatched_preview_origin(
        stage,
        project=project,
        run_id=run_id,
        stage_name=stage_name,
        preview_domain=preview_domain,
    )


__all__ = [
    "DISPATCHING_STEP_RUNNER",
    "dispatched_preview_origin",
    "release_preview_origin",
]

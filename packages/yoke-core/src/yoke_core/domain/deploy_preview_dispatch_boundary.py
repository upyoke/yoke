"""What a run preview's deploy must carry, and where the preview lands.

Two paths stand a release preview up — the flow trigger deploys it directly,
and a project whose previews are published by its own GitHub workflow has
that workflow do it — and a release preview needs the same two things from
either: the frozen candidate to deploy, and a name that does not move while
the candidate is under review.

**One identity names it, whichever path deploys it.** Both derive the
preview from :func:`release_preview_identity`, so one run's preview has one
name and one URL regardless of who stood it up. That also keeps it inside
the reserved slug namespace, which is what a branch cannot reach: naming the
flow path's preview by its readable run id instead put it somewhere a branch
of that name could take over.

Everything project-specific stays configured. Which input carries the
candidate is the stage's own ``inputs`` map, the domain is the project's
``ephemeral-env`` capability, and the derivation from identity to slug is
the substrate's parity contract that the ephemeral-environments Pack
workflow mirrors. Nothing here names a project.

The dispatched path needs one more check the flow path does not: that the
stage, as configured, actually carries those two things to the workflow. A
stage dispatching the deploy workflow without the frozen candidate lets that
workflow resolve its own revision, and the receipt would then read a preview
of something else and call it proof.
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


def release_preview_identity(project: str, run_id: str, stage_name: str) -> str:
    """The one name this run's preview is known by, on every path.

    It is the stage's dispatch correlation because a project's own deploy
    workflow already receives exactly that string and hashes it to name what
    it publishes. Deploying the same preview through the flow path under a
    different identity would give one run's preview two URLs, only one of
    which its receipt ever probes.
    """
    return workflow_dispatch_request_id(project, run_id, stage_name)


def require_dispatch_carries_candidate(
    stage: Mapping[str, Any], *, project: str, stage_name: str
) -> str:
    """Return a refusal if the stage cannot hand the workflow what it needs."""
    step_runner = str(stage.get("step_runner") or "")
    if step_runner != DISPATCHING_STEP_RUNNER:
        return (
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
        return (
            f"stage {stage_name!r} declares dispatch correlation input "
            f"{correlation or 'none'!r}, so the deploy workflow receives no "
            "dispatch identity to name this preview after; a release preview "
            "is addressed by that identity, so set "
            f"dispatch_correlation_input: {WORKFLOW_DISPATCH_CORRELATION_INPUT} "
            "on the stage"
        )
    if not carries_head_sha(workflow_inputs(config)):
        return (
            f"stage {stage_name!r} passes no input carrying this run's frozen "
            "candidate, so the deploy workflow would resolve its own revision "
            "and the receipt would prove a preview of something else; bind the "
            "workflow's revision input to {head_sha}"
        )
    return ""


def release_preview_origin(
    stage: Mapping[str, Any],
    *,
    project: str,
    run_id: str,
    stage_name: str,
    trigger: str,
    preview_domain: str,
) -> tuple[str, str]:
    """Return ``(origin, refusal)`` for this run's preview under *trigger*.

    The origin is the same either way — one run, one preview, one URL. What
    the trigger decides is only whether this stage is able to deploy it.
    """
    if trigger != TRIGGER_FLOW:
        refusal = require_dispatch_carries_candidate(
            stage, project=project, stage_name=stage_name
        )
        if refusal:
            return "", refusal
    if not preview_domain:
        return "", (
            f"project {project!r} configures no preview_domain, so the origin "
            "its previews are published at cannot be derived and nothing could "
            "be probed"
        )
    slug = frozen_preview_slug(
        release_preview_identity(project, run_id, stage_name)
    )
    return preview_url(slug, preview_domain), ""


__all__ = [
    "DISPATCHING_STEP_RUNNER",
    "release_preview_identity",
    "release_preview_origin",
    "require_dispatch_carries_candidate",
]

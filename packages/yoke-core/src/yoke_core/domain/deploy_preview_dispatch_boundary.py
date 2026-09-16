"""What a run preview's deploy must carry, and where the preview lands.

Two paths stand a release preview up — the flow trigger deploys it directly,
and a project whose previews are published by its own GitHub workflow has
that workflow do it — and a release preview needs the same two things from
either: the frozen candidate to deploy, and a name that does not move while
the candidate is under review.

**One recorded identity names it, whichever path deploys it.** Both take the
preview's name from :func:`release_preview_identity`, which is the
deployment run's own id, so one run's preview has one name and one URL
regardless of who stood it up. The name is carried to the deploy workflow
verbatim, as its own input, rather than derived on each side from something
else: naming it after the generic dispatch correlation token instead gave
Yoke and the workflow two different hosts, because that token is scoped to a
dispatch attempt and is replaced before the POST.

Everything project-specific stays configured. Which input carries the
candidate and which carries the preview name are the stage's own ``inputs``
map, and the domain is the project's ``ephemeral-env`` capability. Nothing
here names a project.

The dispatched path needs checks the flow path does not: that the stage, as
configured, actually carries those two things to the workflow. A stage
dispatching the deploy workflow without the frozen candidate lets that
workflow resolve its own revision, and the receipt would then read a preview
of something else and call it proof; a stage that carries no preview name
lets the workflow choose one, which is the drift this contract exists to
close.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    PREVIEW_SLUG_PLACEHOLDER,
    carries_head_sha,
    carries_preview_slug,
    workflow_inputs,
)
from yoke_core.domain.ephemeral_substrate import (
    TRIGGER_FLOW,
    preview_url,
    release_preview_slug,
)

#: One hostname label segment: a discriminator is published as part of the
#: preview's own subdomain, so it may hold nothing a DNS label cannot.
PREVIEW_DISCRIMINATOR_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: The step runner that can carry a frozen candidate and a preview name to a
#: project's own deploy workflow. The other ephemeral step runner deploys a
#: branch from a push and takes neither.
DISPATCHING_STEP_RUNNER = "github-actions-workflow"


def preview_discriminator(stage: Mapping[str, Any]) -> str:
    """The stage's own name for its preview among several in one run."""
    target = stage.get("target") or {}
    if not isinstance(target, Mapping):
        return ""
    return str(target.get("preview_discriminator") or "").strip()


def preview_discriminator_error(value: Any) -> str:
    """Return why *value* cannot be published as a discriminator, or ""."""
    if isinstance(value, str) and PREVIEW_DISCRIMINATOR_RE.fullmatch(value):
        return ""
    return (
        "preview_discriminator must be a lowercase hyphen-separated label; "
        "it is published as part of the preview hostname"
    )


def distinct_previews_error(previews: Sequence[tuple[str, str]]) -> str:
    """Return why these preview stages would collide, or "".

    A release preview is named for its deployment run, which is what keeps
    its URL readable and stable across retries. A run deploying two of them
    therefore needs each stage to say which preview it owns, or both claim
    the same occupancy and the second replaces the first mid-review.
    """
    if len(previews) < 2:
        return ""
    unnamed = sorted(name for name, discriminator in previews if not discriminator)
    if unnamed:
        return (
            f"stages {unnamed} each deploy a release preview in the same run, "
            "so each needs its own target.preview_discriminator; without one "
            "they resolve to the same run-named preview and the second "
            "replaces the first"
        )
    values = [discriminator for _, discriminator in previews]
    if len(set(values)) != len(values):
        return (
            "release preview stages must declare distinct "
            f"target.preview_discriminator values, got {sorted(values)}"
        )
    return ""


def release_preview_identity(stage: Mapping[str, Any], *, run_id: str) -> str:
    """The one name this run's preview is known by, on every path.

    It is the deployment run's id because that is what the preview is a
    preview *of*: it is recorded before anything deploys, it does not move
    while the candidate is reviewed, and it reads as the release in the URL
    a reviewer is sent. A flow that deploys more than one preview in a run
    distinguishes them with each stage's own discriminator.
    """
    return release_preview_slug(run_id, preview_discriminator(stage))


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
            f"{correlation or 'none'!r}, so a dispatch whose response is lost "
            "could not be recovered and would redeploy this run's preview "
            f"blind; set dispatch_correlation_input: "
            f"{WORKFLOW_DISPATCH_CORRELATION_INPUT} on the stage"
        )
    values = workflow_inputs(config)
    if not carries_head_sha(values):
        return (
            f"stage {stage_name!r} passes no input carrying this run's frozen "
            "candidate, so the deploy workflow would resolve its own revision "
            "and the receipt would prove a preview of something else; bind the "
            "workflow's revision input to {head_sha}"
        )
    if not carries_preview_slug(values):
        return (
            f"stage {stage_name!r} passes no input carrying this run's preview "
            "name, so the deploy workflow would name the preview itself and "
            "the receipt would probe a different host than the one deployed; "
            "bind the workflow's preview name input to "
            f"{PREVIEW_SLUG_PLACEHOLDER}"
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
    slug = release_preview_identity(stage, run_id=run_id)
    return preview_url(slug, preview_domain), ""


__all__ = [
    "DISPATCHING_STEP_RUNNER",
    "PREVIEW_DISCRIMINATOR_RE",
    "distinct_previews_error",
    "preview_discriminator",
    "preview_discriminator_error",
    "release_preview_identity",
    "release_preview_origin",
    "require_dispatch_carries_candidate",
]

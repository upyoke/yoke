"""Produce a verified receipt for a deployment run's own preview.

A release run can stand its candidate up on an ephemeral preview and run QA
against it. What makes that preview usable as evidence is not that a deploy
step exited zero — it is that the preview, asked directly, says it is
serving the exact frozen candidate the run pinned.

So this dispatches the stage through the ephemeral machinery the project
already uses, then reads the served revision back over the origin the
project's own preview policy derives. The origin comes from that policy and
the run's identity, never from anything a caller supplies, which is what
makes the answer evidence about *this* run's preview.

The preview is named for the deployment run rather than for a branch: a
release candidate is frozen, and a preview keyed to a branch would move
under it the moment someone pushed.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.deploy_pipeline_stage_receipt_producers import (
    ProducerContext,
    StageObservation,
)


def run_preview_producer(
    context: ProducerContext,
) -> tuple[int, str, Optional[StageObservation]]:
    """Deploy this run's preview, then require it to prove the candidate."""
    from yoke_core.domain.browser_qa_preview_identity import (
        resolve_preview_identity_target,
    )
    from yoke_core.domain.served_revision_probe import probe_served_revision

    target = context.stage.get("target") or {}
    capability = str(target.get("capability") or "")
    if not capability:
        return (
            1,
            f"stage {context.stage_name!r} names no preview capability, so "
            "nothing says where this project publishes previews; give the "
            "stage a run_preview target with a capability",
            None,
        )

    identity = resolve_preview_identity_target(context.project, context.run_id)
    if identity.unreadable:
        return (
            1,
            f"whether project {context.project!r} publishes a preview identity "
            f"proof could not be determined: {identity.unreadable}. That is "
            "unverified rather than unconfigured; restore access to the "
            f"{capability!r} capability and re-run",
            None,
        )
    if not identity.origin:
        return (
            1,
            f"project {context.project!r} configures no identity_path on its "
            f"{capability!r} capability, so its preview cannot be asked which "
            "candidate it serves and no receipt could prove one; set "
            f"identity_path (yoke projects capability-settings merge --project "
            f"{context.project} --cap-type {capability} --set "
            "identity_path=/<path>)",
            None,
        )

    exec_rc, exec_diag = context.dispatch(
        dispatch_environment=context.dispatch_environment
    )
    if exec_rc not in (0, -3):
        return exec_rc, exec_diag, None

    outcome = probe_served_revision(
        identity.origin,
        identity.path,
        expected_sha=context.release_lineage,
    )
    if not outcome.proved:
        return (
            1,
            f"the preview did not prove this candidate: {outcome.kind} "
            f"({outcome.detail}) at {outcome.url}",
            None,
        )
    return (
        exec_rc,
        f"{exec_diag or 'preview deployed'}; the preview served "
        f"{outcome.served} at {outcome.url}",
        StageObservation(
            # The run's own preview, named for the run: the QA stage that
            # consumes this receipt resolves its target from these two
            # fields, and a name borrowed from a branch would drift.
            target_name=context.run_id,
            observed_release_lineage=outcome.served,
            observed_url=identity.origin,
        ),
    )


__all__ = ["run_preview_producer"]

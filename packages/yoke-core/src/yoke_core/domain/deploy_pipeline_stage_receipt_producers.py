"""What a receipt-producing stage dispatch observed, and who can observe it.

:mod:`deploy_pipeline_stage_receipt` owns how a receipt-backed stage is
dispatched and settled; this module owns what a producer *is*. They are
separate because the set of target kinds grows independently of the
dispatch mechanics: registering a producer for a new kind adds an entry
here and touches nothing there.

What a dispatch *observed* and what it *reported* are separate values.
One target kind's producer can read the served URL back, another can read
the served artifact, a third can only lean on its runner's own
verification — so each producer returns a :class:`StageObservation`
alongside its exit code and diagnostic, and the diagnostic travels to the
receipt's ``executor_receipt`` where a human reads it. Feeding a
diagnostic into an observed-identity field instead would make the receipt
store refuse every run that pins the identity, because the store compares
observed against pinned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class StageObservation:
    """What a receipt-producing dispatch actually read back.

    ``target_name`` and ``observed_release_lineage`` are what the receipt
    store requires of every ready receipt. ``observed_url`` and
    ``observed_artifact_identity`` stay empty unless the producer genuinely
    read them: the store compares an observed artifact identity against the
    one the run pins, so a value invented here refuses the receipt.
    """

    target_name: str
    observed_release_lineage: str
    observed_url: str = ""
    observed_artifact_identity: str = ""


@dataclass(frozen=True)
class ProducerContext:
    """Everything a receipt producer may need about the dispatch it owns.

    One typed argument rather than a widening kwarg list, so a producer
    that needs a fact no earlier producer wanted — the QA target's own
    keys, the provider job identity to rejoin, the project whose policy
    resolves a preview — reads it here instead of parsing it back out of
    a diagnostic string. Adding a field touches no existing producer, and
    every producer still names exactly the inputs it uses.

    ``target`` is the *consuming* QA stage's target: it names the kind
    and, on a QA stage, always the ``source_stage`` that produces it —
    ``deployment_flow_policy._validate_target`` requires exactly one of
    ``capability`` or ``source_stage`` and requires ``source_stage`` on a
    QA stage, so a QA target can never carry a kind-specific selector. A
    selector lives on the *producing* stage's own target block, which is
    this stage, reachable as ``context.stage["target"]`` — and the same
    validator guarantees it is there, because a preview-consuming QA
    stage must name an earlier execution stage whose target is a
    ``run_preview`` with a non-empty capability.

    ``dispatch_environment`` is meaningful only to a kind whose target
    names a registered environment; for any other kind it is the run's
    default, which names the wrong thing, and a producer should ignore it.

    ``image_tag`` and ``project_repo_path`` are here because they exist
    nowhere else a producer could read them: the pipeline computes the
    image tag from its resolved product source, and the checkout path is
    driver-local, not a control-plane fact. ``github_repo`` is derivable
    from the project, and is passed anyway because the caller already
    holds it.
    """

    dispatch: Callable[..., tuple[int, str]]
    stage: Mapping[str, Any]
    target: Mapping[str, Any]
    run_id: str
    stage_name: str
    project: str
    correlation_id: str
    dispatch_environment: str
    release_lineage: str
    image_tag: str = ""
    project_repo_path: str = ""
    github_repo: str = ""
    # The origin authorized to answer for this dispatch's target and the
    # path beneath it that serves the revision, both resolved from control
    # plane authority (``deployment_target_identity_config``) rather than
    # from the driver's machine. Empty means this project configures no
    # such proof for persistent targets, which is an answer: the producer
    # falls back to what its step runner verified.
    identity_origin: str = ""
    identity_path: str = ""


#: A producer dispatches one receipt-backed stage and reports what it read.
#: ``None`` for the observation means the dispatch produced no evidence, and
#: the caller settles the receipt as failed.
Producer = Callable[[ProducerContext], "tuple[int, str, Optional[StageObservation]]"]


def _served_revision_observation(
    context: ProducerContext, exec_rc: int, exec_diag: str
) -> tuple[int, str, Optional[StageObservation]]:
    """Ask the environment itself which revision it is now serving.

    This is the project-agnostic proof: whatever deployed the environment,
    the environment answers for itself over the origin its own registered
    row names, at the path its project configured. So a project that
    deploys through its own workflow gets a provable persistent target
    without Yoke-shaped health semantics, and the answer is evidence about
    this environment because neither the origin nor the path can be
    supplied by a caller.
    """
    from yoke_core.domain.served_revision_probe import probe_served_revision

    if not context.identity_origin:
        from yoke_core.domain.environment_registered_url import (
            missing_registered_url_message,
        )

        return (
            exec_rc,
            missing_registered_url_message(
                context.project, context.dispatch_environment
            ),
            None,
        )
    outcome = probe_served_revision(
        context.identity_origin,
        context.identity_path,
        expected_sha=context.release_lineage,
    )
    if not outcome.proved:
        return (
            exec_rc,
            f"the deployed environment did not prove this candidate: "
            f"{outcome.kind} ({outcome.detail}) at {outcome.url}",
            None,
        )
    return (
        exec_rc,
        f"{exec_diag or 'stage completed'}; the environment served "
        f"{outcome.served} at {outcome.url}",
        StageObservation(
            target_name=context.dispatch_environment,
            observed_release_lineage=outcome.served,
        ),
    )


def _runner_verified_observation(
    context: ProducerContext, exec_rc: int, exec_diag: str
) -> tuple[int, str, Optional[StageObservation]]:
    """Take the candidate identity from what the step runner verified.

    Reporting the run's own pinned lineage as *observed* is only honest if
    something actually read the served identity back, so this checks that
    the runner's verification names this candidate rather than trusting
    that it ran: the diagnostic must equal the immutable
    ``canonical_image_tag`` derivation of the pinned lineage, which is what
    health-check asserts the served ``build`` against. Anything else — a
    liveness-only check, a build assertion against an explicitly
    configured tag that is not this candidate's, a branch-HEAD fallback,
    or a runner whose diagnostic is not a candidate identity at all — has
    not observed this candidate, and the caller settles the receipt failed
    rather than recording an unobserved lineage.
    """
    if not exec_diag:
        return exec_rc, exec_diag, None
    from yoke_core.domain.deploy_image_tag import canonical_image_tag

    expected = canonical_image_tag(context.release_lineage)
    if exec_diag.strip() != expected:
        return (
            exec_rc,
            f"the runner verified build {exec_diag.strip()!r}, which does not "
            f"identify this run's pinned candidate (expected {expected!r}); "
            "the served candidate was not observed",
            None,
        )
    return (
        exec_rc,
        exec_diag,
        StageObservation(
            target_name=context.dispatch_environment,
            observed_release_lineage=context.release_lineage,
        ),
    )


def _persistent_environment_producer(
    context: ProducerContext,
) -> tuple[int, str, Optional[StageObservation]]:
    """Dispatch to a registered environment and record what it served.

    Two proofs, one preferred. When the project configures a served
    revision path, the environment is asked directly and its own answer is
    the observation — project-agnostic, and independent of which runner
    deployed it. With no such path configured, the only remaining evidence
    is what the producing step runner itself verified, which is why a
    definition resting on that path is refused unless its runner returns a
    verified candidate identity.

    It reads back no URL of its own (the registered environment's endpoint
    is configuration, which ``deployment_qa_execution_target`` already
    cross-checks) and no artifact identity.
    """
    if context.identity_path and not context.identity_origin:
        from yoke_core.domain.environment_registered_url import (
            missing_registered_url_message,
        )

        return (
            1,
            missing_registered_url_message(
                context.project, context.dispatch_environment
            ),
            None,
        )
    exec_rc, exec_diag = context.dispatch(
        dispatch_environment=context.dispatch_environment
    )
    if exec_rc not in (0, -3):
        return exec_rc, exec_diag, None
    if not context.release_lineage:
        return (
            exec_rc,
            "this run pins no candidate revision, so nothing can identify "
            "the served candidate",
            None,
        )
    if context.identity_path:
        return _served_revision_observation(context, exec_rc, exec_diag)
    return _runner_verified_observation(context, exec_rc, exec_diag)


#: Every target kind this installation can produce a verified receipt for.
def _run_preview_producer(
    context: ProducerContext,
) -> "tuple[int, str, Optional[StageObservation]]":
    """Defer to the preview producer, which owns the ephemeral path."""
    from yoke_core.domain.deploy_preview_receipt_producer import (
        run_preview_producer,
    )

    return run_preview_producer(context)


RECEIPT_PRODUCERS: Dict[str, Producer] = {
    "persistent_environment": _persistent_environment_producer,
    "run_preview": _run_preview_producer,
}

#: Derived from the registry so a new producer cannot leave this behind.
SUPPORTED_TARGET_KINDS = frozenset(RECEIPT_PRODUCERS)

#: Target kinds whose producer genuinely reads the served artifact back. A
#: producer that starts doing so joins this set in the same change; until
#: then a run pinning an artifact identity cannot be receipt-backed for
#: that kind, because nothing could prove the pinned artifact was served.
ARTIFACT_OBSERVING_TARGET_KINDS: frozenset[str] = frozenset()

#: Producing step runners that return a VERIFIED candidate identity, not
#: merely a diagnostic string.
#:
#: This is a narrower claim than "the runner succeeded", and the
#: distinction is the whole point. ``health-check`` earns its place by
#: asserting the served ``build`` against the run's pinned image tag over
#: the Yoke core health contract (build / schema_ready / request-id echo)
#: — a Yoke-core-shaped proof, not a generic one. Every other runner
#: either returns nothing on success or returns prose: a
#: ``github-actions-workflow`` stage, which is how a non-Yoke project
#: ordinarily deploys its own environment, reports what the workflow did
#: and cannot say which revision the target now serves. A health check
#: pointed at an explicit ``url`` returns an empty diagnostic for the same
#: reason: a raw endpoint carries no candidate identity to verify.
#:
#: So this set is what "persistent_environment is supported" actually
#: means today, and it is deliberately not the target kind. A project
#: whose environment is deployed by its own workflow and exposes its own
#: served-revision endpoint needs a producer that reads that endpoint
#: through its configured identity capability; until one is registered
#: here, such a definition is refused before it deploys anything rather
#: than deployed and then unable to settle a receipt.
IDENTITY_PROVING_STEP_RUNNERS: frozenset[str] = frozenset({"health-check"})

#: Target kinds whose producer takes its candidate identity FROM the
#: producing step runner rather than reading the target back itself.
#:
#: For these, :data:`IDENTITY_PROVING_STEP_RUNNERS` is the binding
#: constraint: the producer has no independent way to ask the target what
#: it serves, so an unverified runner means an unprovable receipt. A kind
#: whose producer performs its own readback — a preview whose served
#: commit is fetched over HTTPS — is not listed here, because the runner
#: that deployed it never needed to prove anything.
RUNNER_VERIFIED_TARGET_KINDS: frozenset[str] = frozenset({"persistent_environment"})


__all__ = [
    "ARTIFACT_OBSERVING_TARGET_KINDS",
    "IDENTITY_PROVING_STEP_RUNNERS",
    "RUNNER_VERIFIED_TARGET_KINDS",
    "RECEIPT_PRODUCERS",
    "SUPPORTED_TARGET_KINDS",
    "Producer",
    "ProducerContext",
    "StageObservation",
]

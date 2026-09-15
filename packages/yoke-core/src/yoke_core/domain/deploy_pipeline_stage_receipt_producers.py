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


#: A producer dispatches one receipt-backed stage and reports what it read.
#: ``None`` for the observation means the dispatch produced no evidence, and
#: the caller settles the receipt as failed.
Producer = Callable[
    [ProducerContext], "tuple[int, str, Optional[StageObservation]]"
]


def _persistent_environment_producer(
    context: ProducerContext,
) -> tuple[int, str, Optional[StageObservation]]:
    """Dispatch to a registered environment and record what it served.

    Reporting the run's own pinned lineage as *observed* is only honest if
    something actually read the served identity back, so this producer
    checks that the runner's verification names this candidate rather than
    trusting that it ran: the diagnostic must equal the immutable
    ``canonical_image_tag`` derivation of the pinned lineage, which is what
    health-check asserts the served ``build`` against. Anything else — a
    liveness-only check, a build assertion against an explicitly
    configured tag that is not this candidate's, a branch-HEAD fallback,
    or a runner whose diagnostic is not a candidate identity at all — has
    not observed this candidate, and the caller settles the receipt failed
    rather than recording an unobserved lineage.

    It reads back no URL of its own (the registered environment's endpoint
    is configuration, which ``deployment_qa_execution_target`` already
    cross-checks) and no artifact identity.
    """
    exec_rc, exec_diag = context.dispatch(
        dispatch_environment=context.dispatch_environment
    )
    if exec_rc not in (0, -3) or not exec_diag:
        return exec_rc, exec_diag, None
    if not context.release_lineage:
        return (
            exec_rc,
            "this run pins no candidate revision, so nothing the runner "
            "verified can identify the served candidate",
            None,
        )
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


#: Every target kind this installation can produce a verified receipt for.
RECEIPT_PRODUCERS: Dict[str, Producer] = {
    "persistent_environment": _persistent_environment_producer,
}

#: Derived from the registry so a new producer cannot leave this behind.
SUPPORTED_TARGET_KINDS = frozenset(RECEIPT_PRODUCERS)

#: Target kinds whose producer genuinely reads the served artifact back. A
#: producer that starts doing so joins this set in the same change; until
#: then a run pinning an artifact identity cannot be receipt-backed for
#: that kind, because nothing could prove the pinned artifact was served.
ARTIFACT_OBSERVING_TARGET_KINDS: frozenset[str] = frozenset()


__all__ = [
    "ARTIFACT_OBSERVING_TARGET_KINDS",
    "RECEIPT_PRODUCERS",
    "SUPPORTED_TARGET_KINDS",
    "Producer",
    "ProducerContext",
    "StageObservation",
]

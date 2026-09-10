"""Whether resolving a run's approval stage puts anything into an environment.

Not every gated stage precedes a deploy. A flow can exist so that people can
practise answering an approval, and an internal review can be a genuine
required decision that still reaches no environment -- so telling either
approver "Deploy to merge-only" is a lie about the one thing they are
deciding.

The dangerous half is the inverse. A real production release that happens to
own no work items, or a flow whose NAME says "practice", must never be
dressed up as harmless: a name is prose and an empty batch is routine. So the
answer is derived from three independent facts about the run, every one of
them has to hold, and anything unrecognised counts as deploying.

What is derived here is only the provable consequence -- this stage deploys
nothing -- never why the flow exists. A flow's purpose is whatever its author
named it, which the surfaces already show beside the decision.

The answer is frozen into the approval request's snapshot when the request is
created, beside the release contents, so every reader of that decision sees
the same classification and the evidence that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.flow_validation import VALID_STEP_RUNNERS


#: The step runners that provably reach nothing outside the control plane:
#: one waits for a person, the other records that the stage ran. Every other
#: runner in the vocabulary builds, deploys, activates, probes, or dispatches
#: against a live environment, and an unrecognised name is treated the same
#: way, so a runner added tomorrow is deploying until someone proves it is not.
NON_DEPLOYING_STEP_RUNNERS = frozenset({"auto", "human-approval"})

_UNKNOWN_ALLOWLIST = NON_DEPLOYING_STEP_RUNNERS - VALID_STEP_RUNNERS
if _UNKNOWN_ALLOWLIST:
    raise RuntimeError(
        "non-deploying step runner allowlist names "
        f"{sorted(_UNKNOWN_ALLOWLIST)}, which the flow vocabulary no longer "
        "defines. Recovery: rename the entries in "
        "NON_DEPLOYING_STEP_RUNNERS to match VALID_STEP_RUNNERS."
    )

NON_DEPLOYING_HEADLINE = "Approval only — deploys nothing"

NON_DEPLOYING_EFFECT = (
    "Resolving this records your decision and lets the run finish. Nothing "
    "is built, released, or promoted, no environment changes, and no work "
    "item moves."
)


def _deploying_stages(stages: Sequence[Any]) -> list[str]:
    """Name each stage whose runner is not on the non-deploying allowlist."""
    return [
        f"{stage.name or 'unnamed stage'} runs {stage.step_runner or 'no runner'}"
        for stage in stages
        if str(stage.step_runner or "") not in NON_DEPLOYING_STEP_RUNNERS
    ]


def _carried_work_basis(
    carried: Mapping[str, Any],
    batch_item_count: int,
) -> tuple[bool | None, str]:
    """Answer whether real work ships, and name the evidence for the answer.

    An unanswerable question is not a "no". A run whose contents could not be
    derived may carry every change merged since the last release, so it never
    reaches the non-deploying classification. Evidence that work ships outranks
    that uncertainty: a run owning linked items carries them whether or not
    the lineage comparison could run.
    """
    derivation = carried.get("derivation")
    known = bool(
        isinstance(derivation, Mapping) and derivation.get("contents_known")
    )
    evidence = []
    if len(carried.get("items") or []) or len(carried.get("commits") or []):
        evidence.append("source changes")
    if batch_item_count:
        evidence.append("linked work items")
    if evidence:
        return True, f"This run carries {' and '.join(evidence)}."
    if not known:
        return None, (
            "This run's contents could not be derived, so what it carries "
            "is unknown."
        )
    return False, ""


def derive_release_effect(
    *,
    stages: Sequence[Any],
    target_environment: Any,
    target_tier: Any,
    carried: Mapping[str, Any],
    batch_item_count: int,
    stage: str,
) -> dict[str, Any]:
    """Classify what resolving *stage* does, and record why.

    ``stages`` are the parsed flow stages, ``target_environment`` and
    ``target_tier`` the run's declared destination, and ``carried`` the
    already-derived release contents. The returned object is stored verbatim
    on the approval request.
    """
    deploying = _deploying_stages(stages)
    destination = str(target_environment or target_tier or "").strip()
    carries, carried_basis = _carried_work_basis(carried, batch_item_count)
    deploys = bool(deploying or destination or carries is not False or not stages)
    if not deploys:
        return {
            "deploys": False,
            "headline": NON_DEPLOYING_HEADLINE,
            "effect": NON_DEPLOYING_EFFECT,
            "basis": [
                "No stage in this flow can deploy: every stage runs "
                "human-approval or auto.",
                "The flow names no target environment or tier.",
                "This run carries no source change and owns no work item.",
            ],
        }
    basis = []
    if deploying:
        basis.append("Deploying stages: " + "; ".join(deploying) + ".")
    if destination:
        basis.append(f"The flow targets {destination}.")
    if carried_basis:
        basis.append(carried_basis)
    if not stages:
        basis.append("The flow declares no stages, so what it runs is unknown.")
    return {
        "deploys": True,
        "headline": f"Deploy to {destination or 'merge-only'} — approve the "
                    f"{stage or 'next'} stage",
        "effect": "",
        "basis": basis,
    }


__all__ = [
    "NON_DEPLOYING_EFFECT",
    "NON_DEPLOYING_HEADLINE",
    "NON_DEPLOYING_STEP_RUNNERS",
    "derive_release_effect",
]

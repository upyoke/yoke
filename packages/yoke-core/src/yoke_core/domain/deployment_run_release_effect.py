"""Whether resolving a run's approval stage puts anything into an environment.

Not every gated stage precedes a deploy. A flow can exist so that people can
practise answering an approval, and an internal review can be a genuine
required decision that still reaches no environment -- so telling either
approver "Deploy to merge-only" is a lie about the one thing they are
deciding. "merge-only" is the label a run wears when it names no destination
at all, which is the opposite of a destination.

Three answers, because there are three: this stage deploys, this stage
deploys nothing, and nobody can tell from what the run records. The third is
its own answer and never collapses into either neighbour. Reading an
unrecognised runner as a deploy invents a consequence exactly as reading a
familiar-looking flow as harmless invents safety.

What settles it is the flow's step runners, because they are the mechanism:
a stage either runs something that reaches an environment or it does not.
A destination and a payload are different questions -- where a deploy would
go, and what would ship -- so an unavailable carried-work derivation cannot
make a flow deploy, and an empty release cannot make one harmless. Nor does
"deploys nothing" mean "nothing real": an internal review that reaches no
environment can still be a required decision about genuine work.

Only the provable consequence is derived, never why the flow exists. A
flow's purpose is whatever its author named it, which the surfaces already
show beside the decision.

The answer is frozen into the approval request's snapshot when the request
is created, so every reader of that decision sees the same classification
and the evidence that produced it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from yoke_core.domain.flow_validation import VALID_STEP_RUNNERS


#: The step runners that provably reach nothing outside the control plane:
#: one waits for a person, the other records that the stage ran. Every other
#: runner in the vocabulary builds, deploys, activates, probes, or dispatches
#: against a live environment.
NON_DEPLOYING_STEP_RUNNERS = frozenset({"auto", "human-approval"})

_UNKNOWN_ALLOWLIST = NON_DEPLOYING_STEP_RUNNERS - VALID_STEP_RUNNERS
if _UNKNOWN_ALLOWLIST:
    raise RuntimeError(
        "non-deploying step runner allowlist names "
        f"{sorted(_UNKNOWN_ALLOWLIST)}, which the flow vocabulary no longer "
        "defines. Recovery: rename the entries in "
        "NON_DEPLOYING_STEP_RUNNERS to match VALID_STEP_RUNNERS."
    )

DEPLOYS = "deploys"
DEPLOYS_NOTHING = "deploys_nothing"
UNKNOWN = "unknown"
CONSEQUENCES = (DEPLOYS, DEPLOYS_NOTHING, UNKNOWN)

DEPLOYS_NOTHING_HEADLINE = "Approval only — deploys nothing"

DEPLOYS_NOTHING_EFFECT = (
    "Resolving this records your decision and lets the run finish. No stage "
    "in this flow deploys, so nothing is built, released, or promoted to any "
    "environment. The work this decision governs may still be real."
)

UNKNOWN_EFFECT = (
    "What resolving this puts into an environment could not be established "
    "from what this run records. Read the flow before answering, and treat "
    "it as a decision that may deploy."
)


def _runner(stage: Any) -> str:
    return str(stage.step_runner or "")


def _describe(stage: Any) -> str:
    return f"{stage.name or 'unnamed stage'} runs {_runner(stage) or 'no runner'}"


def derive_release_effect(
    *,
    stages: Sequence[Any],
    target_environment: Any,
    target_tier: Any,
    stage: str,
) -> dict[str, Any]:
    """Classify what resolving *stage* does, and record the evidence for it.

    ``stages`` are the parsed flow stages and ``target_environment`` /
    ``target_tier`` the run's declared destination. The returned object is
    stored verbatim on the approval request.
    """
    known = [entry for entry in stages if _runner(entry) in VALID_STEP_RUNNERS]
    deploying = [
        _describe(entry)
        for entry in known
        if _runner(entry) not in NON_DEPLOYING_STEP_RUNNERS
    ]
    unrecognised = [
        _describe(entry) for entry in stages if _runner(entry) not in VALID_STEP_RUNNERS
    ]
    destination = str(target_environment or target_tier or "").strip()
    stage_label = stage or "next"
    if deploying:
        basis = ["Deploying stages: " + "; ".join(deploying) + "."]
        if destination:
            basis.append(f"The flow targets {destination}.")
        return {
            "consequence": DEPLOYS,
            "headline": (
                f"Deploy to {destination} — approve the {stage_label} stage"
                if destination
                else f"Deploy — approve the {stage_label} stage"
            ),
            "effect": "",
            "basis": basis,
        }
    if unrecognised or not stages or destination:
        basis = []
        if unrecognised:
            basis.append(
                "Stages this build cannot classify: " + "; ".join(unrecognised) + "."
            )
        if not stages:
            basis.append("The flow declares no stages, so what it runs is unknown.")
        if destination:
            basis.append(
                f"The flow targets {destination}, yet no stage in it deploys, "
                "so what reaching that environment means here is not settled."
            )
        return {
            "consequence": UNKNOWN,
            "headline": f"Approve the {stage_label} stage",
            "effect": UNKNOWN_EFFECT,
            "basis": basis,
        }
    return {
        "consequence": DEPLOYS_NOTHING,
        "headline": DEPLOYS_NOTHING_HEADLINE,
        "effect": DEPLOYS_NOTHING_EFFECT,
        "basis": [
            "Every stage runs human-approval or auto, and neither reaches an "
            "environment.",
            "The flow names no target environment or tier.",
        ],
    }


__all__ = [
    "CONSEQUENCES",
    "DEPLOYS",
    "DEPLOYS_NOTHING",
    "DEPLOYS_NOTHING_EFFECT",
    "DEPLOYS_NOTHING_HEADLINE",
    "NON_DEPLOYING_STEP_RUNNERS",
    "UNKNOWN",
    "UNKNOWN_EFFECT",
    "derive_release_effect",
]

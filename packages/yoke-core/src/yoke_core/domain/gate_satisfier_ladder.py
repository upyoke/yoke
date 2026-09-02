"""Ordered satisfier ladders: how a gate names an obligation instead of a shape.

A gate states one OBLIGATION — "prove the committed change stays inside
declared coverage", "prove this item reached done through a merge",
"prove delivery happened", "know which branch integration targets". The
obligation is constant across every project shape. What can *satisfy* it
is not: a project with a remote and CI can prove more than a git-only
repository on one laptop, and a bare folder can prove less than either.

So each obligation carries an ordered ladder of rungs, highest first.
Each rung names the facts it needs. At transition time the ladder
resolves against the project's extended capability registry (declared
capability rows, control-plane-derived facts, and facts observed at the
gate site) and the highest reachable rung is the one that runs. Item-scoped
obligations record which rung answered; a project-scoped lookup with no item
identity must declare itself resolution-only in the ladder model.

Three rules make the mechanism honest, and every consumer inherits them:

* **A rung that cannot resolve is never silently skipped.** When no rung
  is reachable the ladder refuses and the refusal names, per rung, the
  exact fact that was missing.
* **A refusal always names its remedy.** Supplying the missing fact is
  one remedy. Deliberately undeclaring the capability that demanded the
  higher rung is the other, and it is stated explicitly wherever a
  declared capability is what put the unreachable rung on the ladder —
  because "I declared CI and CI is unreachable" is a decision to make,
  not a runtime downgrade to perform.
* **Unknown is not false.** A fact the registry has never observed
  blocks its rung and says so; it does not read as absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from yoke_core.domain.gate_satisfier_facts import CapabilityFacts, FactVerdict


class SatisfierRecordingScope(str, Enum):
    """Where a ladder's resolved rung is durably attributable."""

    ITEM = "item"
    RESOLUTION_ONLY = "resolution_only"


@dataclass(frozen=True)
class SatisfierRung:
    """One way to satisfy an obligation, and what it needs to be reachable."""

    rung_id: str
    summary: str
    requires: Tuple[str, ...] = ()
    #: Capability whose declaration is what puts this rung on the ladder.
    #: Named in the refusal so undeclaring it reads as the sanctioned
    #: downgrade rather than something the runtime may do on its own.
    declared_by_capability: Optional[str] = None


@dataclass(frozen=True)
class SatisfierLadder:
    """An obligation plus the ordered rungs that can discharge it."""

    obligation: str
    statement: str
    rungs: Tuple[SatisfierRung, ...]
    #: What an operator does when no rung is reachable and no capability
    #: undeclaration applies.
    remedy: str
    #: Item-scoped gates stamp their rung. Project-scoped lookups that have no
    #: item identity must declare why they are resolution-only.
    recording_scope: SatisfierRecordingScope = SatisfierRecordingScope.ITEM
    recording_reason: str = ""

    def __post_init__(self) -> None:
        if (
            self.recording_scope is SatisfierRecordingScope.RESOLUTION_ONLY
            and not self.recording_reason.strip()
        ):
            raise ValueError(
                f"resolution-only ladder {self.obligation!r} must explain "
                "why it has no durable item stamp"
            )

    def rung(self, rung_id: str) -> SatisfierRung:
        for candidate in self.rungs:
            if candidate.rung_id == rung_id:
                return candidate
        raise KeyError(f"ladder {self.obligation!r} has no rung {rung_id!r}")


@dataclass(frozen=True)
class RungRejection:
    """Why one rung was not the answer."""

    rung_id: str
    missing_fact: str
    verdict: str
    detail: str


@dataclass(frozen=True)
class LadderResolution:
    """The outcome of resolving one ladder against one fact registry."""

    obligation: str
    rung: Optional[SatisfierRung]
    rejected: Tuple[RungRejection, ...] = ()
    facts: Dict[str, str] = field(default_factory=dict)

    @property
    def satisfied(self) -> bool:
        return self.rung is not None

    @property
    def rung_id(self) -> str:
        return self.rung.rung_id if self.rung else ""


class LadderUnsatisfied(Exception):
    """No rung of the ladder was reachable.

    ``message`` is the operator-facing narrative: the obligation, every
    rung that was considered with the fact it lacked, and the remedy.
    """

    def __init__(self, resolution: LadderResolution, message: str) -> None:
        super().__init__(message)
        self.resolution = resolution
        self.message = message


def resolve_ladder(
    ladder: SatisfierLadder,
    facts: CapabilityFacts,
) -> LadderResolution:
    """Return the highest reachable rung, or a resolution with none.

    Rungs are evaluated in declaration order, so the ladder author's
    ordering IS the precedence. A rung is reachable when every fact it
    requires is present; a fact that is absent or unknown rejects the
    rung and the reason is retained for the refusal narrative.
    """
    rejected: List[RungRejection] = []
    for rung in ladder.rungs:
        blocker = _first_missing_fact(rung.rung_id, rung.requires, facts)
        if blocker is None:
            return LadderResolution(
                obligation=ladder.obligation,
                rung=rung,
                rejected=tuple(rejected),
                facts=facts.snapshot(),
            )
        rejected.append(blocker)
    return LadderResolution(
        obligation=ladder.obligation,
        rung=None,
        rejected=tuple(rejected),
        facts=facts.snapshot(),
    )


def _first_missing_fact(
    rung_id: str,
    requires: Sequence[str],
    facts: CapabilityFacts,
) -> Optional[RungRejection]:
    """Return the first fact that puts ``rung_id`` out of reach."""
    for key in requires:
        verdict = facts.verdict(key)
        if verdict is FactVerdict.PRESENT:
            continue
        return RungRejection(
            rung_id=rung_id,
            missing_fact=key,
            verdict=verdict.value,
            detail=facts.explain(key),
        )
    return None


def require_rung(
    ladder: SatisfierLadder,
    facts: CapabilityFacts,
) -> LadderResolution:
    """Resolve the ladder or raise :class:`LadderUnsatisfied`.

    Consumers that must never fail open call this instead of
    :func:`resolve_ladder`, so the absence of a reachable rung surfaces
    as a diagnosed refusal rather than a pass.
    """
    resolution = resolve_ladder(ladder, facts)
    if resolution.satisfied:
        return resolution
    raise LadderUnsatisfied(resolution, render_refusal(ladder, resolution))


def render_refusal(
    ladder: SatisfierLadder,
    resolution: LadderResolution,
) -> str:
    """Render the operator-facing narrative for an unsatisfiable ladder."""
    lines = [
        f"No satisfier is reachable for obligation {ladder.obligation!r}.",
        ladder.statement,
        "",
        "Rungs considered, highest first:",
    ]
    undeclarable: List[str] = []
    for rejection in resolution.rejected:
        rung = ladder.rung(rejection.rung_id)
        lines.append(
            f"  - {rejection.rung_id}: {rung.summary}\n"
            f"    needs {rejection.missing_fact} "
            f"({rejection.verdict}) — {rejection.detail}"
        )
        if rung.declared_by_capability:
            undeclarable.append(rung.declared_by_capability)
    lines.append("")
    lines.append(f"Remedy: {ladder.remedy}")
    for capability in dict.fromkeys(undeclarable):
        lines.append(
            f"Remedy: the {capability!r} capability is what puts a rung "
            "this project cannot reach on the ladder. If that capability "
            "no longer describes this project, undeclare it — "
            "`yoke projects capability-settings remove --project <SLUG> "
            f"--cap-type {capability} --base <SETTINGS-AS-READ>` — "
            "and the ladder drops to the rung the project can actually "
            "satisfy. Undeclaring is an operator decision; the runtime "
            "will never make it silently."
        )
    return "\n".join(lines)


__all__ = [
    "LadderResolution",
    "LadderUnsatisfied",
    "RungRejection",
    "SatisfierLadder",
    "SatisfierRecordingScope",
    "SatisfierRung",
    "render_refusal",
    "require_rung",
    "resolve_ladder",
]

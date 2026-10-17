"""How each live deployment run is doing, for the seat that has to decide.

A run that stalls says nothing. Its stage stays "current", its obligations
stay unresolved, and no surface answers "has this been at this stage for
four hours, and is any of it red" — so the only remedy anyone reached for
was to cancel the run, which strands its members and discards re-authored
waivers.

The facts were already readable. A run sitting at a scoped QA stage
asks :func:`qa_stage_outstanding` — the same walk a drive uses, without
writing — so the outstanding count cannot disagree with the stage gate.
Off that stage, ``unresolved_blocking_qa`` and
``blocking_obligation_total`` in
:mod:`deployment_run_completion_preconditions` still answer the
completion-boundary question. This detector adds the stage age and the
red requirements with the members they belong to, whether each waiting
item-QA member's owner was woken, and renders one row per live run.

It decides nothing. There is no timeout and no auto-cancel here on
purpose: a run that has been at a stage for hours is *reported*, and a
person reads the row and chooses. The only rows marked as needing action
are the ones the run cannot leave by itself — a determinate failing
verdict, a resolved decision the runner has not acted on, and a run
still at ``created`` with nothing outstanding and no live driver. A
``created`` run with a live driver is already inside a silent phase
(the self-deploy freeze is the worked case). An ``executing`` run with
nothing outstanding is already being driven: the row names the stage it
is at rather than recommending a second drive.

A red requirement whose member has a recorded merge outside this run's
``release_lineage`` is named as unable to pass against the pin, with
superseding as the path. That comparison is containment of the recorded
merge, never elapsed time or a newer tip. An unreadable comparison is
named as unproven rather than asserted.
"""

from __future__ import annotations


from datetime import datetime

from dataclasses import dataclass
from typing import Optional

from yoke_core.domain.deployment_qa_manual_wake import (
    ManualWakeRequirement,
)
from yoke_core.domain.deployment_run_completion_preconditions import redrive_recovery
from yoke_core.domain.deployment_run_red_requirements import RedRequirement
from yoke_core.domain.deployment_run_unpassable_blocking_qa import (
    PinQaDiagnosis,
)
from yoke_core.domain.deployment_run_completion_preview import (
    CompletionPreview,
)
from yoke_core.domain.runs import RunStatus


@dataclass(frozen=True)
class AnsweredDecision:
    """A stage decision a person answered that the run never acted on.

    The decision surface records the answer; the deployment runner is the
    only thing that advances run state, and nothing re-drives the run when
    an answer arrives. So the stage keeps waiting on a question that has
    already been settled, and the person who settled it has no signal that
    their answer did nothing.

    Not read from ``consumed_at``: that column is written only by the item
    lifecycle's own approval consumption, never for a deployment stage, so
    it is NULL on every one of these rows and proves nothing either way.
    What establishes the gap is the pair of live facts — this stage has a
    resolved decision, and the run is still sitting on this stage.
    """

    request_id: int
    action: str
    resolved_at: datetime | None
    resolved_seconds: Optional[int]

    def describe(self) -> str:
        verb = "rejected" if self.action == "reject" else "approved"
        return f"decision #{self.request_id} {verb}"


@dataclass(frozen=True)
class DeploymentRunProgress:
    """One live run's stage, age, and outstanding blocking QA."""

    run_id: str
    flow: str
    status: str
    stage: str
    #: Seconds since the run's durable current-stage entry timestamp.
    #: ``None`` means the stage age is unknown, including older runs.
    stage_seconds: Optional[int]
    outstanding: int
    total_blocking: int
    unresolved: tuple[str, ...]
    red: tuple[RedRequirement, ...]
    #: Set when this run's current stage already has a resolved decision.
    answered_decision: Optional[AnsweredDecision] = None
    pin_qa: PinQaDiagnosis = PinQaDiagnosis()
    #: Live driver phase when one is attached, else empty. Distinguishes
    #: "nobody started this" from "started, inside a long silent phase".
    driver_phase: str = ""
    no_obligation_lines: tuple[str, ...] = ()
    #: One line per waiting item-QA member: how many blockers it holds and
    #: whether its owner was woken. The per-requirement detail stays on
    #: ``yoke deployment-runs stages RUN``.
    member_lines: tuple[str, ...] = ()
    completion: CompletionPreview = CompletionPreview()
    #: Open manual-wake requirements of waiting members: steering, not the
    #: stage, wakes their owners once the named evidence exists.
    manual_wakes: tuple[ManualWakeRequirement, ...] = ()

    @property
    def needs_action(self) -> bool:
        """True when nothing the run is waiting for can arrive by itself.

        Outstanding QA is not that signal on its own. A run still at
        ``created`` with nothing outstanding is waiting to be driven only
        when no live driver is attached; a live driver in a silent freeze
        is already in flight even while status stays ``created``. One
        already ``executing`` with nothing outstanding is in flight, and
        recommending a re-drive there invites a second dispatch against a
        live release.
        """
        waiting_to_be_driven = (
            self.status == RunStatus.CREATED
            and self.outstanding == 0
            and not self.driver_phase
        )
        return (
            self.completion.blocked
            or bool(self.red)
            or self.answered_decision is not None
            or waiting_to_be_driven
        )

    def recovery(self) -> str:
        if recovery := self.completion.recovery(self.run_id):
            return recovery
        if self.driver_phase:
            return f"Live driver {self.driver_phase} owns this run; read its progress before recovery."
        if self.pin_qa.unpassable:
            return self.pin_qa.supersede_recovery(self.run_id)
        if self.status == RunStatus.CREATED and self.outstanding == 0:
            return f"Nothing is outstanding; re-drive {self.run_id} to start it."
        if self.answered_decision is not None:
            return (
                f"Answer recorded; re-drive {self.run_id} so the runner acts on it: "
                "an approve proceeds, a reject fails the stage."
            )
        return redrive_recovery(self.run_id, unresolved=self.outstanding)


__all__ = [
    "AnsweredDecision",
    "DeploymentRunProgress",
]

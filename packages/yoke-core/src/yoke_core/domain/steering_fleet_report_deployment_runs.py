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
red requirements with the members they belong to, and renders one row
per live run.

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

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
from yoke_core.domain.deployment_run_completion_preconditions import redrive_recovery
from yoke_core.domain.deployment_run_driver_attachment import live_attachment_for_run
from yoke_core.domain.deployment_run_unpassable_blocking_qa import (
    PinQaDiagnosis,
    diagnose_unpassable_blocking_qa,
)
from yoke_core.domain.runs import RunStatus
from yoke_core.domain.steering_fleet_report_deployment_run_facts import (
    live_deployment_runs,
    load_live_run_facts,
    probe_report_tables,
)
from yoke_core.domain.steering_fleet_report_detectors import age_seconds


@dataclass(frozen=True)
class RedRequirement:
    """One blocking requirement whose latest verdict is a determinate failure."""

    requirement_id: int
    verdict: str
    #: The run member this requirement was scoped to, empty for a run-wide one.
    member_ref: str = ""

    def describe(self) -> str:
        subject = self.member_ref or "run-wide"
        return f"{subject} #{self.requirement_id} {self.verdict}"


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
    resolved_at: str
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
    #: Seconds since this stage's most recent receipt, or since the run
    #: started when the stage has produced none. ``None`` when neither is
    #: readable — reported as unknown rather than guessed at as zero.
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
            bool(self.red) or self.answered_decision is not None or waiting_to_be_driven
        )

    def recovery(self) -> str:
        if self.pin_qa.unpassable:
            return self.pin_qa.supersede_recovery(self.run_id)
        if self.answered_decision is not None:
            return (
                f"The answer is already recorded; re-drive {self.run_id} so the "
                "runner acts on it — an approve proceeds, a reject fails the "
                "stage. Until then the run waits on a settled question."
            )
        return redrive_recovery(self.run_id, unresolved=self.outstanding)


def _answered(raw: Optional[dict[str, Any]], *, now: str) -> Optional[AnsweredDecision]:
    if raw is None:
        return None
    resolved_at = str(raw.get("resolved_at") or "")
    return AnsweredDecision(
        request_id=int(raw["request_id"]),
        action=str(raw.get("action") or ""),
        resolved_at=resolved_at,
        resolved_seconds=age_seconds(resolved_at, now),
    )


def run_progress(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[DeploymentRunProgress, ...]:
    """Every non-terminal run in the project, with what is holding it."""
    tables = probe_report_tables(conn)
    if not tables.has("deployment_runs"):
        return ()
    live = live_deployment_runs(conn, project_id=project_id)
    if not live:
        return ()
    facts = load_live_run_facts(conn, runs=live, tables=tables)
    rows = []
    for run in live:
        run_id = str(run["id"])
        stage = str(run["current_stage"])
        qa = (
            qa_stage_outstanding(conn, run_id=run_id, stage_name=stage)
            if run_id in facts.qa_stage_run_ids
            else None
        )
        if qa is not None:
            unresolved = qa.lines
            outstanding = qa.waiting
            total_blocking = qa.subjects
        else:
            unresolved = facts.unresolved.get(run_id, ())
            outstanding = len(unresolved)
            total_blocking = facts.totals.get(run_id, 0)
        entered = facts.entered_at.get(run_id) or str(
            run.get("started_at") or run.get("created_at") or ""
        )
        red = tuple(
            RedRequirement(
                requirement_id=int(item["requirement_id"]),
                verdict=str(item["verdict"]),
                member_ref=str(item.get("member_ref") or ""),
            )
            for item in facts.red.get(run_id, ())
        )
        attached = live_attachment_for_run(conn, run_id_value=run_id, now=now)
        rows.append(
            DeploymentRunProgress(
                run_id=run_id,
                flow=str(run["flow"] or ""),
                status=str(run["status"] or ""),
                stage=stage or "unstarted",
                stage_seconds=age_seconds(entered, now),
                outstanding=outstanding,
                total_blocking=total_blocking,
                unresolved=unresolved,
                red=red,
                answered_decision=_answered(facts.decisions.get(run_id), now=now),
                pin_qa=(
                    diagnose_unpassable_blocking_qa(conn, run_id=run_id)
                    if red
                    else PinQaDiagnosis()
                ),
                driver_phase=attached.phase if attached is not None else "",
            )
        )
    return tuple(rows)


__all__ = [
    "AnsweredDecision",
    "DeploymentRunProgress",
    "RedRequirement",
    "run_progress",
]

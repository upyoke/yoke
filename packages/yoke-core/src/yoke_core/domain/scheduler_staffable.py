"""Which ranked steps a newly launched worker could actually advance.

Every workflow binds a skill to its ``release`` stage, so the frontier ranks a
landed item waiting only for its next release as runnable. A worker launched
onto it finds nothing to do: the release, the close-out, or the holder of its
epic's task owns what is left. The scheduler's selected step and the steering
report's available section both ask :func:`is_staffable`, so neither offers a
step the other would refuse.

A landed item stays staffable only when a worker still owes it something: a
re-landing after rework sent it back, or the item QA or red verdict a live
deployment run waits on. Landing and live-run membership come from the same
readers the report's landed and run sections use; nothing here is new state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .delivery_landing_custody import merged_open_items
from .scheduler_claims import _evaluate_claim_states
from .scheduler_types import (
    ClaimState,
    NextStep,
    ScheduledStep,
    is_assignable_claim_state,
)
from .session_item_stage_rework import items_returned_after_landing


@dataclass(frozen=True)
class StaffingFacts:
    """What decides whether an assignable step has work left for a new worker."""

    #: Items whose branch landed while the item stayed open.
    landed: frozenset[int] = frozenset()
    #: Landed items a worker still owes a re-landing, item QA or a red verdict.
    owed: frozenset[int] = frozenset()
    #: Epics a live session of another worker is working a task of.
    task_held: frozenset[int] = frozenset()


def owes_relanding(status: str, returned_after_landing: bool) -> bool:
    """Rework sent the landed item back before release; it must land again."""
    return returned_after_landing and status != "release"


def is_staffable(
    step: ScheduledStep,
    *,
    conduct_eligible_ids: Iterable[int],
    facts: StaffingFacts,
) -> bool:
    """Whether a new worker launched onto ``step`` could advance it."""
    if step.next_step is NextStep.WAIT:
        return False
    if (
        step.next_step is NextStep.CONDUCT
        and step.item_id not in set(conduct_eligible_ids)
    ):
        return False
    if step.item_id in facts.task_held:
        return False
    return step.item_id not in facts.landed or step.item_id in facts.owed


def staffable_steps(
    conn: Any,
    steps: Sequence[ScheduledStep],
    *,
    project_scope: Sequence[int],
    conduct_eligible_ids: Iterable[int],
    session_id: str | None,
) -> list[ScheduledStep]:
    """Assignable ``steps``, in rank order, that a new worker could advance."""
    candidates = [step for step in steps if is_assignable_claim_state(step.claim_state)]
    facts = read_staffing_facts(
        conn,
        [step.item_id for step in candidates],
        project_scope=project_scope,
        session_id=session_id,
    )
    eligible = frozenset(int(item_id) for item_id in conduct_eligible_ids)
    return [
        step
        for step in candidates
        if is_staffable(step, conduct_eligible_ids=eligible, facts=facts)
    ]


def read_staffing_facts(
    conn: Any,
    item_ids: Sequence[int],
    *,
    project_scope: Sequence[int],
    session_id: str | None,
) -> StaffingFacts:
    """Landing, owed work and task holders for these candidate items.

    Live runs are read only when a landed candidate owes no re-landing,
    because only then can run membership change the answer.
    """
    wanted = {int(item_id) for item_id in item_ids}
    if not wanted:
        return StaffingFacts()
    landed = {
        int(record["id"]): record
        for project_id in project_scope
        for record in merged_open_items(conn, int(project_id))
        if int(record["id"]) in wanted
    }
    returned = items_returned_after_landing(conn, landed) if landed else set()
    relanding = {
        item_id
        for item_id, record in landed.items()
        if owes_relanding(str(record.get("status") or ""), item_id in returned)
    }
    unowed = set(landed) - relanding
    run_owed = _live_run_owed(conn, project_scope) & unowed if unowed else set()
    task_claims = _evaluate_claim_states(
        conn, sorted(wanted), session_id=session_id, target_kind="epic_task"
    )
    return StaffingFacts(
        landed=frozenset(landed),
        owed=frozenset(relanding | run_owed),
        task_held=frozenset(
            item_id
            for item_id, state in task_claims.items()
            if state is ClaimState.CLAIMED_BY_OTHER_LIVE
        ),
    )


def _live_run_owed(conn: Any, project_scope: Sequence[int]) -> set[int]:
    """Members a live run waits on for item QA, or holds a red verdict for."""
    from .deployment_qa_stage_outstanding import qa_stage_outstanding
    from .deployment_run_red_requirements import red_blocking_requirements
    from .steering_fleet_report_deployment_run_facts import (
        live_deployment_runs,
        probe_report_tables,
    )

    if not probe_report_tables(conn).has("deployment_runs"):
        return set()
    runs = [
        run
        for project_id in project_scope
        for run in live_deployment_runs(conn, project_id=int(project_id))
    ]
    owed: set[int] = set()
    for run in runs:
        if not run["current_stage"]:
            continue
        qa = qa_stage_outstanding(
            conn, run_id=str(run["id"]), stage_name=str(run["current_stage"])
        )
        if qa is not None:
            owed.update(int(member) for member in qa.waiting_members if member)
    red = red_blocking_requirements(conn, [str(run["id"]) for run in runs])
    owed.update(
        int(requirement.item_id)
        for requirements in red.values()
        for requirement in requirements
        if requirement.item_id
    )
    return owed


__all__ = [
    "StaffingFacts",
    "is_staffable",
    "owes_relanding",
    "read_staffing_facts",
    "staffable_steps",
]

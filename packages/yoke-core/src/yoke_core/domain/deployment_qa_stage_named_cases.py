"""Does a deployment QA stage subject already name concrete cases of its own?

``--plan`` on ``yoke qa plan run`` exists for the one story where nobody has
chosen anything yet: a stage that names no cases, whose responsible agent
picks a project QA plan to fill it. Every other subject already carries the
cases it will be credited for -- pinned in the flow's stage config, frozen
into the run's admission snapshot, attached to the member, admitted from the
member's own post-deploy obligations, or authored directly onto the stage.

Adding a plan to one of those does not select cases; it materializes a
SECOND set beside the ones the stage already counts, which the stage then
waits on as extra unsatisfied obligations. So the question "does this
subject already name cases?" has to be answerable before the agent plan is
folded in, and the same answer decides whether a wake's recipe should print
``--plan`` at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_qa_direct_case_target import (
    list_direct_deployment_method_cases,
)


AGENT_PLAN_ALREADY_NAMED_REFUSAL = (
    "this deployment QA stage already names its cases, so an "
    "agent-selected plan would materialize a second, duplicate set of "
    "obligations beside the ones the stage credits. Re-run the same "
    "command without --plan; --plan selects cases only for a stage that "
    "names none, which is the wait that asks you for one by name."
)


def stage_names_cases(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    frozen_plans: list[dict[str, Any]],
    admitted: list[dict[str, Any]],
) -> bool:
    """True when this run/stage/member subject already carries cases.

    *frozen_plans* is what the flow, the run snapshot, or the member
    attachment already selected; *admitted* is the member's own frozen
    post-deploy obligations. Both are read by the caller anyway, so they
    are passed in rather than re-derived. Only the directly authored
    cases need a query of their own.

    Rows an earlier agent selection materialized are deliberately NOT
    counted. Re-supplying the same plan is how a corrected plan case
    reaches a subject that already has rows
    (:mod:`qa_deployment_case_content_refresh`), so refusing there would
    take away the repair rather than the duplicate.
    """
    if isinstance(subject["stage"].get("cases"), Mapping):
        return True
    if frozen_plans:
        return True
    if any(requirement.get("method_id") for requirement in admitted):
        return True
    return bool(
        list_direct_deployment_method_cases(
            conn,
            run_id=str(subject["id"]),
            stage=str(subject["stage"]["name"]),
            member_item_id=subject.get("member_item_id"),
        )
    )


__all__ = [
    "AGENT_PLAN_ALREADY_NAMED_REFUSAL",
    "stage_names_cases",
]

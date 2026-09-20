"""Empty QA plan roster: discharged without cases vs never asked.

``ordered_plan_requirements`` used to refuse every empty roster the same
way. The stage gate already distinguishes a recorded no-obligation (or
waiver-backed none) from silence, via
:func:`member_post_deploy_answer`. This module is that distinction at the
roster boundary: the plan runner still does not discharge the stage; it
tells the owner the recorded answer already did.
"""

from __future__ import annotations

from typing import Any, Mapping, NoReturn

from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

DISCHARGED_BEGIN_CODE = "plan_execution_already_discharged"
DISCHARGED_PLAN_STATE = "discharged_without_cases"


class QaPlanRosterDischarged(QaPlanExecutionError):
    """The empty roster is a recorded no-obligation, not a missing plan."""

    def __init__(
        self,
        message: str,
        *,
        requirement_id: int,
        qa_kind: str,
    ) -> None:
        super().__init__(message)
        self.requirement_id = int(requirement_id)
        self.qa_kind = str(qa_kind)


def discharged_without_cases_statement(
    *, requirement_id: int, qa_kind: str
) -> str:
    """Owner-facing fact: this member's stage is already satisfied."""
    return (
        f"This member's stage is already satisfied: requirement "
        f"#{int(requirement_id)} records {qa_kind}, which discharges the "
        "stage without cases. Steering re-drives the run and the stage "
        "gate reads that discharge. Do not run anything else; there is "
        "nothing for this member to run."
    )


def recorded_discharge(
    conn: Any, item_id: int
) -> tuple[int, str] | None:
    """The requirement row the stage gate would read as discharging."""
    from yoke_core.domain.db_helpers import query_rows
    from yoke_core.domain.post_deploy_verification_answer import (
        NO_OBLIGATION_QA_KIND,
    )
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        DEPLOYMENT_ATTACHMENT_PHASE,
    )

    rows = query_rows(
        conn,
        "SELECT id,qa_kind,qa_phase,waived_at FROM qa_requirements "
        "WHERE item_id=%s AND deployment_run_id IS NULL",
        (int(item_id),),
    )
    mapped = [_row(row) for row in rows]
    no_obligation = [
        row
        for row in mapped
        if str(row.get("qa_phase") or "") == DEPLOYMENT_ATTACHMENT_PHASE
        and str(row.get("qa_kind") or "") == NO_OBLIGATION_QA_KIND
        and not row.get("waived_at")
    ]
    if no_obligation:
        row = no_obligation[0]
        return int(row["id"]), str(row["qa_kind"])
    declared = [
        row
        for row in mapped
        if str(row.get("qa_phase") or "") == DEPLOYMENT_ATTACHMENT_PHASE
        and row.get("waived_at")
        and str(row.get("qa_kind") or "") != NO_OBLIGATION_QA_KIND
    ]
    if declared:
        row = declared[0]
        return int(row["id"]), str(row["qa_kind"])
    return None


def member_discharge_statement(conn: Any, item_id: int) -> str | None:
    """Wake-body clause when the member already discharges without cases."""
    from yoke_core.domain.post_deploy_verification_answer import answer_for_item

    answer = answer_for_item(conn, int(item_id))
    if not answer.discharges_without_cases:
        return None
    record = recorded_discharge(conn, int(item_id))
    if record is None:
        return (
            "This member's stage is already satisfied: a recorded "
            f"{answer.verdict} answer discharges the stage without cases. "
            "Steering re-drives the run and the stage gate reads that "
            "discharge. Do not run anything else; there is nothing for "
            "this member to run."
        )
    return discharged_without_cases_statement(
        requirement_id=record[0], qa_kind=record[1]
    )


def refuse_empty_roster(
    conn: Any,
    *,
    deployment_member_item_id: int | None,
    subject: str,
) -> NoReturn:
    """Never returns: the empty roster is either discharge or a miss."""
    if deployment_member_item_id is not None:
        from yoke_core.domain.post_deploy_verification_answer import (
            answer_for_item,
            cases_not_selected_refusal,
        )
        from yoke_core.domain.project_identity import render_item_ref

        answer = answer_for_item(conn, int(deployment_member_item_id))
        if answer.discharges_without_cases:
            record = recorded_discharge(conn, int(deployment_member_item_id))
            qa_kind = record[1] if record is not None else answer.verdict
            requirement_id = record[0] if record is not None else 0
            statement = discharged_without_cases_statement(
                requirement_id=requirement_id, qa_kind=qa_kind
            )
            raise QaPlanRosterDischarged(
                statement,
                requirement_id=requirement_id,
                qa_kind=qa_kind,
            )
        member_ref = render_item_ref(conn, int(deployment_member_item_id))
        raise QaPlanExecutionError(
            f"{subject} has no materialized QA cases. "
            f"{cases_not_selected_refusal(member_ref=member_ref)}"
        )
    raise QaPlanExecutionError(f"{subject} has no materialized QA cases")


def as_discharged_plan_result(exc: BaseException) -> dict[str, Any] | None:
    """Turn a discharged begin refusal into a successful plan-run result."""
    text = str(exc)
    prefix = f"qa.plan_execution.begin failed ({DISCHARGED_BEGIN_CODE}): "
    if not text.startswith(prefix):
        return None
    return {
        "state": DISCHARGED_PLAN_STATE,
        "message": text[len(prefix) :],
        "requirements": [],
        "results": [],
    }


def _row(row: Any) -> Mapping[str, Any]:
    if hasattr(row, "keys"):
        return dict(row)
    return {}


__all__ = [
    "DISCHARGED_BEGIN_CODE",
    "DISCHARGED_PLAN_STATE",
    "QaPlanRosterDischarged",
    "as_discharged_plan_result",
    "discharged_without_cases_statement",
    "member_discharge_statement",
    "recorded_discharge",
    "refuse_empty_roster",
]

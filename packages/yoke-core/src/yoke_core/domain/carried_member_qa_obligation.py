"""Item QA eligibility for members delivered by another project's release."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow
from yoke_core.domain.post_deploy_verification_answer import answer_for_item
from yoke_core.domain.qa_item_stage_plan_gate import stages_declare_item_scoped_qa
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql


def carried_member_no_item_qa_reason(conn: Any, *, run_id: str, item_id: int) -> str:
    """Empty unless a carried member owes no item QA under its own flow.

    Silence only qualifies when the member's own flow could not have asked
    it. Explicit item plans, intake obligations, and run-bound method cases
    remain obligations regardless of that flow's stage declarations.
    """
    rows = query_rows(
        conn,
        "SELECT i.project_id AS member_project_id, dr.project_id "
        "FROM items i JOIN deployment_run_items dri ON dri.item_id=i.id "
        "JOIN deployment_runs dr ON dr.id=dri.run_id "
        "WHERE dr.id=%s AND i.id=%s",
        (str(run_id), int(item_id)),
    )
    if not rows or int(rows[0]["project_id"]) == int(rows[0]["member_project_id"]):
        return ""
    if not answer_for_item(conn, int(item_id)).unanswered:
        return ""
    if query_rows(
        conn,
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL "
        f"AND {unretracted_requirement_sql(conn)} LIMIT 1",
        (str(run_id), int(item_id)),
    ):
        return ""
    flow = item_completion_flow(conn, int(item_id))
    if not flow:
        return ""  # An unreadable or unresolved flow never proves emptiness.
    flows = query_rows(conn, "SELECT stages FROM deployment_flows WHERE id=%s", (flow,))
    if not flows or stages_declare_item_scoped_qa(flows[0]["stages"]):
        return ""
    return (
        f"no item QA obligation: cross-project member's own completion flow "
        f"{flow!r} declares no item-scoped QA stage"
    )


def stage_no_item_qa_reason(conn: Any, subject: Mapping[str, Any]) -> str:
    """The exemption also preserves any cases selected for this stage."""
    member = subject.get("member_item_id")
    if member is None or subject["stage"].get("scope") != "item":
        return ""
    if subject.get("member_project_id") == subject.get("project_id"):
        return ""
    reason = carried_member_no_item_qa_reason(
        conn, run_id=str(subject["id"]), item_id=int(member)
    )
    if not reason:
        return ""
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_frozen_plan_selection import (
        frozen_stage_plans,
        member_requirements,
    )
    from yoke_core.domain.deployment_qa_stage_named_cases import stage_names_cases

    target = deployment_qa_execution_target(conn, subject)
    admitted = member_requirements(conn, subject, target=target)
    frozen = frozen_stage_plans(conn, subject, target=target, admitted=admitted)
    if stage_names_cases(conn, subject, frozen_plans=frozen, admitted=admitted):
        return ""
    return reason

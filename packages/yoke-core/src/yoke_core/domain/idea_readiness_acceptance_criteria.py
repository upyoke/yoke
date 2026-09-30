"""Acceptance criteria are required at the pinned Refine handoff."""

from typing import Any

from yoke_core.domain.idea_readiness_results import Issue
from yoke_core.domain.prd_validate import Report, check_acceptance_criteria
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def verify_refine_acceptance_criteria(
    conn: Any, item_id: int, spec: str
) -> list[Issue]:
    row = conn.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()
    if row is None:
        return []
    status = str(row[0])
    workflow = load_item_workflow_runtime(conn, item_id)
    binding = workflow.skill_binding_for_stage(status)
    if (
        not binding
        or binding["skill_id"] != "refine"
        or status == binding["from_stage_id"]
    ):
        return []
    report = Report()
    check_acceptance_criteria(spec, report)
    if not report.fail_count:
        return []
    ref = render_item_ref(conn, item_id)
    return [
        Issue(
            code="MISSING_ACCEPTANCE_CRITERIA",
            message=f"{ref}: {report.failures[0]}",
            remediation=(
                "Add an Acceptance Criteria section with independently testable "
                "checkboxes to this item's spec, then rerun yoke readiness check "
                f"{ref} before leaving refinement."
            ),
        )
    ]

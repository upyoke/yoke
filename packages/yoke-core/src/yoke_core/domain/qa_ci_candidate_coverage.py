"""Current candidate CI proof covers earlier passing candidates of one item.

This is a read-time settlement rule, not a rewrite of historical requirements
or runs. Only stale commit identity may be discharged; every other refusal
and every non-CI method keeps its own evidence obligation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoke_core.domain.qa_terminal_settlement import BlockingRequirementIssue


def _scope(row: dict[str, Any]) -> tuple[Any, ...] | None:
    if (
        row.get("method_id") != "command-ci"
        or row.get("qa_phase") != "verification"
        or row.get("deployment_run_id")
        or row.get("deployment_member_item_id")
    ):
        return None
    # Callers supply an item-scoped roster; item_id also separates explicitly
    # identified owners when a composed roster carries those fields.
    return row.get("item_id"), row.get("workflow_transition_id"), row["qa_phase"]


def covered_stale_ci_ids(
    graded: list[tuple[dict[str, Any], BlockingRequirementIssue | None]],
) -> set[str]:
    """Older successful CI rows answered by a newer exact-candidate pass.

    The caller grades all rows normally first. A covering row must have no
    issue, a real code identity and a current completed pass; waived,
    retracted or replaced rows are excluded by the caller before grading.
    """
    passing: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row, issue in graded:
        scope = _scope(row)
        if (
            scope is not None
            and issue is None
            and row.get("verdict") == "pass"
            and row.get("completed_at") is not None
            and row.get("recorded_head_sha")
            and row.get("requires_code_identity") is not False
        ):
            passing.setdefault(scope, []).append(row)
    return {
        str(row["id"])
        for row, issue in graded
        if issue is not None
        and issue.state == "stale-sha"
        and row.get("verdict") == "pass"
        and row.get("recorded_head_sha")
        for successor in passing.get(_scope(row), [])
        if int(successor["id"]) > int(row["id"])
        and int(successor["run_id"]) > int(row["run_id"])
    }

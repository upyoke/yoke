"""Authoritative materialized-case lookup for Machine QA baseline groups."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.handlers.test_machine_case import _is_machine_case


def baseline_group_cases(
    conn: Any,
    *,
    anchor: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reread one materialized baseline group from database authority."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )

    plan_id = anchor.get("plan_id")
    baseline = str(anchor.get("host_baseline") or "")
    if plan_id is None or not baseline:
        raise ValueError(
            "baseline-group execution requires a plan-backed Machine QA "
            "requirement with a host baseline"
        )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    method_ids = sorted(MACHINE_METHODS)
    item_id = anchor.get("item_id")
    deployment_run_id = anchor.get("deployment_run_id")
    if bool(item_id) == bool(deployment_run_id):
        raise ValueError("baseline-group requirement has no unique QA subject")
    subject_column = "item_id" if item_id is not None else "deployment_run_id"
    subject_value: int | str = (
        int(item_id) if item_id is not None else str(deployment_run_id)
    )
    rows = conn.execute(
        "SELECT id FROM qa_requirements "
        f"WHERE {subject_column}={marker} AND plan_id={marker} "
        f"AND COALESCE(workflow_transition_id, '')={marker} "
        f"AND host_baseline={marker} AND waived_at IS NULL "
        f"AND method_id IN ({', '.join(marker for _ in method_ids)}) "
        "ORDER BY case_position, baseline_position, id",
        (
            subject_value,
            int(plan_id),
            str(anchor.get("workflow_transition_id") or ""),
            baseline,
            *method_ids,
        ),
    ).fetchall()
    cases = [
        get_case_execution_context(conn, requirement_id=int(row[0])) for row in rows
    ]
    anchor_id = int(anchor["requirement_id"])
    if not cases or anchor_id not in {int(case["requirement_id"]) for case in cases}:
        raise ValueError(
            "the targeted requirement is not in its materialized baseline group"
        )
    if any(
        not _is_machine_case(case)
        or case.get("item_id") != anchor.get("item_id")
        or case.get("deployment_run_id") != anchor.get("deployment_run_id")
        or int(case["plan_id"]) != int(plan_id)
        or str(case.get("workflow_transition_id") or "")
        != str(anchor.get("workflow_transition_id") or "")
        or str(case.get("host_baseline") or "") != baseline
        for case in cases
    ):
        raise ValueError("the materialized baseline group changed during execution")
    return cases


__all__ = ["baseline_group_cases"]

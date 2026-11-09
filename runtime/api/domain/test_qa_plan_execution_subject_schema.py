"""Permanent coverage for item and deployment-run plan execution subjects."""

from __future__ import annotations


from yoke_core.domain.qa_plan_execution_schema import (
    assert_qa_plan_execution_subject_invariants,
    converge_qa_plan_execution_subject_schema,
)


def test_subject_convergence_is_idempotent(test_db) -> None:
    converge_qa_plan_execution_subject_schema(test_db)
    assert_qa_plan_execution_subject_invariants(test_db)
    converge_qa_plan_execution_subject_schema(test_db)
    assert_qa_plan_execution_subject_invariants(test_db)

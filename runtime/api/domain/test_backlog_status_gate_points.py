"""Definition-owned lifecycle-gate placement and dispatch guards."""

from __future__ import annotations

import inspect

from yoke_core.domain import backlog_authoritative_status_gate
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)


def _gate_ids(workflow_id: str, stage_id: str) -> tuple[str, ...]:
    definition = builtin_workflow_definition(workflow_id)["definition"]
    stage = next(
        stage for stage in definition["stages"] if stage["id"] == stage_id
    )
    return tuple(gate["id"] for gate in stage["gates"])


def test_issue_definition_owns_gate_placement():
    assert _gate_ids("issue", "refining-idea") == (
        "db_claim_prose",
        "db_mutation",
    )
    assert _gate_ids("issue", "implemented") == (
        "db_claim_prose",
        "db_mutation",
        "architecture_impact",
        "path_claim_boundary",
        "qa_verification",
    )


def test_epic_definition_adds_plan_simulation_only_to_planned():
    assert "plan_simulation" in _gate_ids("epic", "planned")
    assert "plan_simulation" not in _gate_ids("issue", "refined-idea")


def test_direct_workflows_can_place_distinct_closure_gates():
    assert "doc_completion" in _gate_ids("blitz", "done")
    assert "dash_evidence" in _gate_ids("dash", "done")
    assert "doc_completion" not in _gate_ids("issue", "done")
    assert "dash_evidence" not in _gate_ids("epic", "done")


def test_composer_reads_the_pinned_definition_and_registered_gate_ids():
    source = inspect.getsource(backlog_authoritative_status_gate)

    assert "load_item_workflow_runtime" in source
    assert "workflow.gates_for_stage(target_status)" in source
    assert "backlog_status_gate_points" not in source
    for evaluator in (
        "_run_db_mutation_gate",
        "_run_architecture_impact_gate",
        "check_boundary_for_item",
        "_evaluate_plan_simulation",
        "_evaluate_qa_verification",
    ):
        assert evaluator in source

"""Task-graph and shepherd gates hold on a plain lifecycle transition."""

from __future__ import annotations

from runtime.api.domain.structural_status_gate_test_helpers import (
    insert_item,
    insert_task,
    runtime_for,
)
from yoke_core.domain.deferred_item_tracking import (
    UNFILED_ENTRY,
    UNTRACKED_DEFERRAL,
    deferral_findings,
)
from yoke_core.domain.workflow_task_graph_status_gates import (
    evaluate_deferred_items,
    evaluate_shepherd_verdict,
    evaluate_task_completion,
    evaluate_task_existence,
    implementation_binding,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def _run(evaluator, conn, item_id, target):
    return evaluator(
        conn=conn,
        item_id=item_id,
        target_status=target,
        workflow=runtime_for(conn, item_id),
    )


def test_epic_implementation_binding_is_the_task_executor():
    binding = implementation_binding(builtin_workflow_runtime("epic"))
    assert binding is not None
    assert binding["skill_id"] == "conduct"


def test_task_graph_must_exist_from_the_executing_binding_on(gate_conn):
    insert_item(gate_conn, 70, workflow="epic", status="refining-plan")
    assert _run(evaluate_task_existence, gate_conn, 70, "plan-drafted") is None
    failure = _run(evaluate_task_existence, gate_conn, 70, "planned")
    assert failure is not None
    assert failure["error_code"] == "GATE_EPIC_TASKS"
    assert "/yoke shepherd" in failure["remediation_hint"]
    insert_task(gate_conn, 70, 1, "planned")
    assert _run(evaluate_task_existence, gate_conn, 70, "planned") is None


def test_single_lane_workflows_own_no_task_graph(gate_conn):
    insert_item(gate_conn, 71, workflow="dash", status="idea")
    assert _run(evaluate_task_existence, gate_conn, 71, "implementing") is None
    assert _run(evaluate_task_completion, gate_conn, 71, "release") is None


def test_parent_leaves_task_execution_only_after_every_task(gate_conn):
    insert_item(gate_conn, 72, workflow="epic", status="implementing")
    insert_task(gate_conn, 72, 1, "reviewed-implementation")
    insert_task(gate_conn, 72, 2, "implementing")
    assert (
        _run(evaluate_task_completion, gate_conn, 72, "reviewing-implementation")
        is None
    )
    failure = _run(evaluate_task_completion, gate_conn, 72, "reviewed-implementation")
    assert failure is not None
    assert failure["error_code"] == "GATE_EPIC_TASKS_INCOMPLETE"
    assert "task 2 (implementing)" in failure["error"]
    assert "task 1" not in failure["error"]
    gate_conn.execute(
        "UPDATE epic_tasks SET status = 'reviewed-implementation' "
        "WHERE epic_id = 72 AND task_num = 2"
    )
    assert (
        _run(evaluate_task_completion, gate_conn, 72, "reviewed-implementation") is None
    )
    assert _run(evaluate_task_completion, gate_conn, 72, "done") is None


def test_completion_refuses_an_empty_task_graph(gate_conn):
    insert_item(gate_conn, 73, workflow="epic", status="reviewing-implementation")
    failure = _run(evaluate_task_completion, gate_conn, 73, "reviewed-implementation")
    assert failure is not None
    assert "no generated tasks exist" in failure["error"]


def test_unfiled_deferral_refuses_successful_completion(gate_conn):
    spec = "## Deferred Items\n- Retry budget (UNFILED)\n"
    insert_item(gate_conn, 74, workflow="epic", status="release", spec=spec)
    failure = _run(evaluate_deferred_items, gate_conn, 74, "done")
    assert failure is not None
    assert failure["error_code"] == "GATE_DEFERRED_ITEMS_UNFILED"
    assert "UNFILED" in failure["error"]
    assert "/yoke idea" in failure["remediation_hint"]
    assert _run(evaluate_deferred_items, gate_conn, 74, "release") is None


def test_filed_deferrals_complete(gate_conn):
    spec = (
        "## Deferred Items\n- Retry budget: YOK-901\n\nDeferred to follow-up YOK-901.\n"
    )
    insert_item(gate_conn, 75, workflow="epic", status="release", spec=spec)
    assert _run(evaluate_deferred_items, gate_conn, 75, "done") is None


def test_deferral_findings_ignore_fences_and_filed_refs():
    assert deferral_findings("") == ()
    assert deferral_findings("Deferred to follow-up work.") == (UNTRACKED_DEFERRAL,)
    assert deferral_findings("Deferred to follow-up in PLAT-12.") == ()
    assert deferral_findings("```\ndeferred to follow-up\n```") == ()
    assert deferral_findings("## Deferred Items\n- x unfiled\n## Next\n") == (
        UNFILED_ENTRY,
    )


def _verdict(conn, item_id, transition, verdict):
    conn.execute(
        "INSERT INTO shepherd_verdicts (item, transition, worker, verdict, "
        "created_at) VALUES (%s, %s, 'architect', %s, '2026-10-05')",
        (f"YOK-{item_id}", transition, verdict),
    )
    conn.commit()


def test_shepherd_verdict_gates_the_start_of_implementation(gate_conn):
    insert_item(gate_conn, 76, workflow="epic", status="planned")
    insert_task(gate_conn, 76, 1, "planned")
    assert _run(evaluate_shepherd_verdict, gate_conn, 76, "planned") is None
    failure = _run(evaluate_shepherd_verdict, gate_conn, 76, "implementing")
    assert failure is not None
    assert failure["error_code"] == "GATE_SHEPHERD_VERDICT"
    _verdict(gate_conn, 76, "planning_to_plan_drafted", "NEEDS_WORK")
    assert _run(evaluate_shepherd_verdict, gate_conn, 76, "implementing") is not None
    _verdict(gate_conn, 76, "planning_to_plan_drafted", "READY")
    assert _run(evaluate_shepherd_verdict, gate_conn, 76, "implementing") is None


def test_definitions_without_shepherd_owe_no_verdict(gate_conn):
    insert_item(gate_conn, 77, workflow="issue", status="refined-idea")
    assert _run(evaluate_shepherd_verdict, gate_conn, 77, "implementing") is None

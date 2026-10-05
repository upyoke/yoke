"""Delivery gates hold on a plain lifecycle transition for every workflow."""

from __future__ import annotations

import json

from runtime.api.domain.structural_status_gate_test_helpers import (
    insert_dependency,
    insert_item,
    runtime_for,
)
from yoke_core.domain import workflow_structural_status_gates as composer
from yoke_core.domain.workflow_delivery_status_gates import (
    activation_stage_index,
    evaluate_delivery_flow,
    evaluate_dependency_edges,
    evaluate_merge_record,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def _deps(conn, item_id, target):
    return evaluate_dependency_edges(
        conn=conn,
        item_id=item_id,
        target_status=target,
        workflow=runtime_for(conn, item_id),
        db_path="",
    )


def test_activation_stage_is_the_lane_taking_stage():
    for workflow_id in ("dash", "issue", "blitz", "task"):
        runtime = builtin_workflow_runtime(workflow_id)
        assert runtime.stage_ids[activation_stage_index(runtime)] == "implementing"


def test_dash_activation_edge_refuses_implementing(gate_conn):
    insert_item(gate_conn, 10, workflow="dash", status="idea")
    insert_item(gate_conn, 20, workflow="dash", status="idea")
    insert_dependency(gate_conn, 20, 10, "activation", "fact:merged")
    failure = _deps(gate_conn, 20, "implementing")
    assert failure is not None
    assert failure["error_code"] == "GATE_HARD_BLOCKS_UNSATISFIED"
    assert "gated at activation" in failure["error"]


def test_activation_edge_holds_at_later_working_stages(gate_conn):
    insert_item(gate_conn, 10, workflow="dash", status="idea")
    insert_item(gate_conn, 20, workflow="dash", status="implementing")
    insert_dependency(gate_conn, 20, 10, "activation", "fact:merged")
    assert _deps(gate_conn, 20, "reviewing-implementation") is not None


def test_integration_edge_holds_only_where_a_merge_is_implied(gate_conn):
    insert_item(gate_conn, 10, workflow="dash", status="idea")
    insert_item(gate_conn, 20, workflow="dash", status="idea")
    insert_dependency(gate_conn, 20, 10, "integration", "fact:merged")
    assert _deps(gate_conn, 20, "implementing") is None
    failure = _deps(gate_conn, 20, "release")
    assert failure is not None
    assert "gated at integration" in failure["error"]


def test_listed_activation_gate_is_not_evaluated_twice(gate_conn, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.workflow_activation_status_gates.evaluate_check_hard_blocks",
        lambda **kwargs: calls.append(kwargs["gate_point"]),
    )
    insert_item(gate_conn, 30, workflow="issue", status="refined-idea")
    _deps(gate_conn, 30, "implementing")
    _deps(gate_conn, 30, "reviewing-implementation")
    assert calls == ["activation"]


def test_pinned_item_flow_satisfies_the_delivery_gate(gate_conn):
    insert_item(gate_conn, 40, workflow="dash", status="idea")
    workflow = runtime_for(gate_conn, 40)
    gate_conn.execute("UPDATE items SET deployment_flow = 'fixture-flow' WHERE id = 40")
    assert (
        evaluate_delivery_flow(
            conn=gate_conn,
            item_id=40,
            target_status="implementing",
            workflow=workflow,
        )
        is None
    )


def test_delivery_flow_refusal_names_the_missing_default(gate_conn, monkeypatch):
    from yoke_core.domain import deployment_item_flow_resolution as flows

    insert_item(gate_conn, 41, workflow="dash", status="idea")
    monkeypatch.setattr(
        flows,
        "item_completion_flow_facts",
        lambda conn, ids: {
            41: flows.ItemCompletionFlowFact("", flows.FLOW_SOURCE_NONE)
        },
    )
    failure = evaluate_delivery_flow(
        conn=gate_conn,
        item_id=41,
        target_status="implementing",
        workflow=runtime_for(gate_conn, 41),
    )
    assert failure is not None
    assert failure["error_code"] == "GATE_DELIVERY_FLOW_UNRESOLVED"
    assert "delivery-default set" in failure["error"]
    assert "retry the transition" in failure["error"]
    assert "items scalar update" in failure["remediation_hint"]


def test_merge_free_delivery_owes_no_flow(gate_conn):
    insert_item(gate_conn, 42, workflow="task", status="idea")
    assert (
        evaluate_delivery_flow(
            conn=gate_conn,
            item_id=42,
            target_status="implementing",
            workflow=runtime_for(gate_conn, 42),
        )
        is None
    )


def _merge(conn, item_id, target="release"):
    return evaluate_merge_record(
        conn=conn,
        item_id=item_id,
        target_status=target,
        workflow=runtime_for(conn, item_id),
    )


def test_release_wait_requires_a_recorded_landing(gate_conn):
    insert_item(gate_conn, 50, workflow="dash", status="reviewing-implementation")
    failure = _merge(gate_conn, 50)
    assert failure is not None
    assert failure["error_code"] == "GATE_MERGE_UNRECORDED"
    assert "yoke merge item" in failure["remediation_hint"]
    assert _merge(gate_conn, 50, target="reviewing-implementation") is None
    gate_conn.execute(
        "UPDATE items SET merged_at = '2026-10-05T00:00:00Z' WHERE id = 50"
    )
    assert _merge(gate_conn, 50) is None


def test_attested_no_change_result_needs_no_landing(gate_conn):
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION

    insert_item(gate_conn, 51, workflow="dash", status="reviewing-implementation")
    gate_conn.execute(
        "INSERT INTO item_sections (item_id, section_name, content, ordering, "
        "created_at, updated_at) VALUES (%s, %s, %s, 300, '2026-10-05', "
        "'2026-10-05')",
        (51, DASH_EVIDENCE_SECTION, json.dumps({"no_changes": True})),
    )
    assert _merge(gate_conn, 51) is None


def test_force_keeps_only_the_never_bypassed_gates(gate_conn):
    insert_item(gate_conn, 10, workflow="dash", status="idea")
    insert_item(gate_conn, 60, workflow="dash", status="reviewing-implementation")
    insert_dependency(gate_conn, 60, 10, "integration", "fact:merged")
    kwargs = dict(
        conn=gate_conn,
        item_id=60,
        target_status="release",
        workflow=runtime_for(gate_conn, 60),
        db_path="",
    )
    assert composer.evaluate(force=False, **kwargs) is not None
    assert composer.evaluate(force=True, **kwargs) is None


def test_exceptional_stages_carry_no_structural_obligation(gate_conn):
    insert_item(gate_conn, 61, workflow="dash", status="implementing")
    assert (
        composer.evaluate(
            conn=gate_conn,
            item_id=61,
            target_status="blocked",
            workflow=runtime_for(gate_conn, 61),
            force=False,
            db_path="",
        )
        is None
    )

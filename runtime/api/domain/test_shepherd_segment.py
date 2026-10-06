"""Renamed and extended planning segments retain their own verdict obligations."""

from copy import deepcopy
from dataclasses import replace

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain.shepherd_gate import check_gate
from yoke_core.domain.shepherd_segment import shepherd_edges
from yoke_core.domain.workflow_registry import (
    WorkflowRegistryError,
    publish_workflow_version,
)
from yoke_core.domain.workflow_runtime import (
    builtin_workflow_runtime,
    load_item_workflow_runtime,
)
from yoke_core.engines.doctor_hc_meta_lifecycle import hc_shepherd_lifecycle
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.done_transition_preconditions import evaluate_done_preconditions


def _renamed_definition():
    definition = deepcopy(builtin_workflow_runtime("epic").definition)
    names = {
        "refined-idea": "spec-ready",
        "planning": "plan-writing",
        "plan-drafted": "plan-handoff",
    }
    for stage in definition["stages"]:
        stage["id"] = names.get(stage["id"], stage["id"])
    for row in definition["transitions"] + definition["skill_bindings"]:
        for field in ("from_stage_id", "to_stage_id", "through_stage_id"):
            if field in row:
                row[field] = names.get(row[field], row[field])
    definition["stage_mapping"] = {
        stage["id"]: names.get(stage["id"], stage["id"])
        for stage in builtin_workflow_runtime("epic").stages
    }
    return definition


def _runtime(definition):
    return replace(builtin_workflow_runtime("epic"), definition=definition)


def test_edges_follow_renamed_binding():
    edges = shepherd_edges(_runtime(_renamed_definition()))
    assert [
        (edge.source_stage, edge.target_stage, edge.verdict_key) for edge in edges
    ] == [
        ("spec-ready", "plan-writing", "spec_ready_to_plan_writing"),
        ("plan-writing", "plan-handoff", "plan_writing_to_plan_handoff"),
    ]


def test_edges_follow_added_review_stage():
    definition = _renamed_definition()
    position = next(
        i
        for i, stage in enumerate(definition["stages"])
        if stage["id"] == "plan-handoff"
    )
    definition["stages"].insert(position, {"id": "plan-check", "gates": []})
    for row in definition["transitions"]:
        if row["from_stage_id"] == "plan-writing":
            row["to_stage_id"] = "plan-check"
    definition["transitions"].append(
        {"from_stage_id": "plan-check", "to_stage_id": "plan-handoff"}
    )
    assert [edge.verdict_key for edge in shepherd_edges(_runtime(definition))] == [
        "spec_ready_to_plan_writing",
        "plan_writing_to_plan_check",
        "plan_check_to_plan_handoff",
    ]


def test_single_edge_segment_uses_one_plan_and_review_key():
    definition = _renamed_definition()
    binding = next(
        row for row in definition["skill_bindings"] if row["skill_id"] == "shepherd"
    )
    binding["through_stage_id"] = "plan-writing"
    assert len(shepherd_edges(_runtime(definition))) == 1


def test_missing_declared_edge_refuses_with_recovery():
    definition = _renamed_definition()
    definition["transitions"] = [
        row
        for row in definition["transitions"]
        if row["from_stage_id"] != "plan-writing"
    ]
    with pytest.raises(
        WorkflowRegistryError, match="shepherd_segment_unsupported: publish"
    ):
        shepherd_edges(_runtime(definition))


def test_no_shepherd_binding_owns_no_edges():
    assert shepherd_edges(builtin_workflow_runtime("issue")) == ()


def _verdict(conn, item_id, edge, verdict="READY", worker="review"):
    conn.execute(
        "INSERT INTO shepherd_verdicts (public_ref, transition, worker, verdict, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (f"YOK-{item_id}", edge.verdict_key, worker, verdict, "2026-10-05T00:00:00Z"),
    )
    conn.commit()


def test_all_consumers_accept_only_pinned_edge_evidence(test_db):
    definition = _renamed_definition()
    published = publish_workflow_version(
        test_db, workflow_id="epic", definition=definition
    )
    item_id = 987
    insert_item(
        test_db,
        id=item_id,
        title="Renamed planning",
        workflow_id="epic",
        status="plan-handoff",
        spec="body",
    )
    test_db.execute(
        "UPDATE items SET workflow_version_id = %s WHERE id = %s",
        (published["version_id"], item_id),
    )
    test_db.commit()
    edges = shepherd_edges(load_item_workflow_runtime(test_db, item_id))
    # A canonical key from a different pin is not this item's evidence.
    old_edges = shepherd_edges(builtin_workflow_runtime("epic"))
    for edge in old_edges:
        _verdict(test_db, item_id, edge)
    assert not check_gate(item_id, conn=test_db).passed
    allowed, reason = evaluate_done_preconditions(test_db, item_id, "", True)
    assert not allowed and edges[0].verdict_key in reason
    rec = RecordCollector()
    hc_shepherd_lifecycle(test_db, DoctorArgs(), rec)
    assert rec.results[0].result == "WARN"
    assert edges[0].verdict_key in rec.results[0].detail

    _verdict(test_db, item_id, edges[0])
    assert evaluate_done_preconditions(test_db, item_id, "", True) == (True, None)
    rec = RecordCollector()
    hc_shepherd_lifecycle(test_db, DoctorArgs(), rec)
    assert edges[-1].verdict_key in rec.results[0].detail
    _verdict(test_db, item_id, edges[-1], verdict="SKIPPED", worker="Designer")
    assert not check_gate(item_id, conn=test_db).passed
    rec = RecordCollector()
    hc_shepherd_lifecycle(test_db, DoctorArgs(), rec)
    assert rec.results[0].result == "WARN"
    _verdict(test_db, item_id, edges[-1])
    assert check_gate(item_id, conn=test_db).passed
    rec = RecordCollector()
    hc_shepherd_lifecycle(test_db, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS"

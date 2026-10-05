"""A transition with attached cases owes them even where QA is unlisted."""

from __future__ import annotations

from runtime.api.domain.structural_status_gate_test_helpers import (
    insert_item,
    runtime_for,
)
from yoke_core.domain import qa_attached_transition_gate as gate


def _requirement(conn, item_id, transition, *, blocking="blocking") -> int:
    row = conn.execute(
        "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, "
        "blocking_mode, created_at, workflow_transition_id) "
        "VALUES (%s, 'browser', 'verification', %s, '2026-10-05', %s) "
        "RETURNING id",
        (item_id, blocking, transition),
    ).fetchone()
    conn.commit()
    return int(row[0])


def _run(conn, item_id, target):
    return gate.evaluate(
        conn=conn,
        item_id=item_id,
        target_status=target,
        workflow=runtime_for(conn, item_id),
    )


def test_unlisted_stage_refuses_its_own_unrun_cases(gate_conn):
    insert_item(gate_conn, 80, workflow="dash", status="implementing")
    requirement_id = _requirement(gate_conn, 80, "reviewing-implementation")
    failure = _run(gate_conn, 80, "reviewing-implementation")
    assert failure is not None
    assert failure["error_code"] == "GATE_QA_ATTACHED_TRANSITION"
    assert f"Requirement #{requirement_id}" in failure["error"]
    assert "yoke qa plan run" in failure["remediation_hint"]


def test_cases_bound_to_another_transition_do_not_block(gate_conn):
    insert_item(gate_conn, 81, workflow="dash", status="implementing")
    _requirement(gate_conn, 81, "release")
    _requirement(gate_conn, 81, "reviewing-implementation", blocking="non_blocking")
    assert _run(gate_conn, 81, "reviewing-implementation") is None


def test_a_stage_listing_qa_verification_is_left_to_the_listed_gate(gate_conn):
    insert_item(gate_conn, 82, workflow="dash", status="reviewing-implementation")
    _requirement(gate_conn, 82, "release")
    assert _run(gate_conn, 82, "release") is None

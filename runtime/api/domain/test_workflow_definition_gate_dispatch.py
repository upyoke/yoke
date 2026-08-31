"""Definition-owned lifecycle-gate placement and dispatch guards."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import backlog_authoritative_status_gate
from yoke_core.domain import direct_workflow_gate_dispatch
from yoke_core.domain.conflict_survey import record_conflict_survey, survey_conflicts
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.item_worktrees import list_item_worktrees, record_item_worktree
from yoke_core.domain.strategy_docs_create import create_doc
from yoke_core.domain.strategy_execution import active_strategy_doc_claim, link_execution_document
from yoke_core.domain.strategy_execution_schema import ensure_strategy_execution_schema
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION, LANE_WORKER
from yoke_core.domain.work_claim_targets import make_item_target


def _gate_ids(workflow_id: str, stage_id: str) -> tuple[str, ...]:
    definition = builtin_workflow_definition(workflow_id)["definition"]
    stage = next(stage for stage in definition["stages"] if stage["id"] == stage_id)
    return tuple(gate["id"] for gate in stage["gates"])


def test_issue_definition_owns_gate_placement():
    assert _gate_ids("issue", "refining-idea") == ("db_claim_prose", "db_mutation")
    assert _gate_ids("issue", "implemented") == ("db_claim_prose", "db_mutation", "architecture_impact", "path_claim_boundary", "qa_verification")


def test_epic_definition_adds_plan_simulation_only_to_planned():
    assert "plan_simulation" in _gate_ids("epic", "planned")
    assert "plan_simulation" not in _gate_ids("issue", "refined-idea")


def test_direct_workflows_can_place_distinct_closure_gates():
    assert "doc_completion" in _gate_ids("blitz", "done")
    assert "dash_evidence" in _gate_ids("dash", "done")
    assert "floor_attestation" in _gate_ids("task", "done")
    assert "doc_completion" not in _gate_ids("issue", "done")
    assert "dash_evidence" not in _gate_ids("epic", "done")


def test_composer_reads_the_pinned_definition_and_registered_gate_ids():
    source = inspect.getsource(backlog_authoritative_status_gate)

    assert "load_item_workflow_runtime" in source
    assert "workflow.gates_for_stage(target_status)" in source
    for evaluator in (
        "_run_db_mutation_gate",
        "_run_architecture_impact_gate",
        "check_boundary_for_item",
        "_evaluate_plan_simulation",
        "_evaluate_qa_verification",
        "direct_workflow_gate_dispatch",
    ):
        assert evaluator in source


def test_every_direct_and_approval_gate_has_an_executable_dispatch():
    gate_ids = {"work_claim_activation", "doc_claim_activation", "conflict_survey", "doc_completion", "dash_evidence", "floor_attestation", "approval"}
    assert all(direct_workflow_gate_dispatch.handles(value) for value in gate_ids)
    source = inspect.getsource(direct_workflow_gate_dispatch)
    for evaluator_module in ("direct_workflow_activation_gate", "conflict_survey_gate", "doc_completion_gate", "dash_evidence_gate", "floor_attestation_gate", "approval_status_gate"):
        assert evaluator_module in source


@pytest.fixture
def direct_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            ensure_strategy_execution_schema(conn)
        finally:
            conn.close()
        yield db_path


def _seed_activation(db_path: str, *, item_id: int, workflow_id: str, session_id: str, lane_role: str, touch_path: str) -> None:
    conn = connect_test_db(db_path)
    try:
        insert_item(conn, id=item_id, workflow_id=workflow_id, status="idea" if workflow_id == "dash" else "refined-idea")
        now = iso8601_now()
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, workspace, project_id, "
            "offered_at, last_heartbeat, actor_id) "
            "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s, 1)",
            (session_id, now, now),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
            (session_id, make_item_target(item_id).scope_json(), now, now),
        )
        record_item_worktree(conn, item_id=item_id, branch=f"YOK-{item_id}", path=f"/tmp/YOK-{item_id}", lane_role=lane_role)
        survey = survey_conflicts(conn, item_id=item_id, touch_paths=[touch_path])
        assert survey.clear is True
        record_conflict_survey(conn, survey)
        conn.commit()
    finally:
        conn.close()


def _run_implementing_gate(db_path: str, *, item_id: int, session_id: str) -> dict | None:
    return backlog_authoritative_status_gate._run_authoritative_status_gate(
        item_id=item_id, target_status="implementing", db_path=db_path, qa_bypass=False, force=False, session_id=session_id
    )


def test_dash_activation_requires_the_live_claim_and_registered_worktree(direct_db_path: str, monkeypatch: pytest.MonkeyPatch):
    from yoke_core.domain import backlog_architecture_gate_runner

    monkeypatch.setattr(backlog_architecture_gate_runner, "_run_architecture_impact_gate", lambda **_kwargs: None)
    _seed_activation(
        direct_db_path, item_id=2170, workflow_id="dash", session_id="dash-activation", lane_role=LANE_IMPLEMENTATION, touch_path="src/dash_activation.py"
    )

    assert _run_implementing_gate(direct_db_path, item_id=2170, session_id="dash-activation") is None

    conn = connect_test_db(direct_db_path)
    try:
        conn.execute("UPDATE item_worktrees SET state='released', released_at=%s WHERE item_id=2170 AND state='active'", (iso8601_now(),))
        conn.commit()
    finally:
        conn.close()
    blocked = _run_implementing_gate(direct_db_path, item_id=2170, session_id="dash-activation")
    assert blocked["error_code"] == "GATE_WORK_CLAIM_ACTIVATION_UNSATISFIED"
    assert "no active registered worktree lane" in blocked["error"]


def test_blitz_lifecycle_claims_refuses_conflict_and_releases_terminally(direct_db_path: str, monkeypatch: pytest.MonkeyPatch):
    from yoke_core.domain import backlog_architecture_gate_runner

    monkeypatch.setattr(backlog_architecture_gate_runner, "_run_architecture_impact_gate", lambda **_kwargs: None)
    _seed_activation(direct_db_path, item_id=2180, workflow_id="blitz", session_id="blitz-owner", lane_role=LANE_WORKER, touch_path="src/blitz_owner.py")
    conn = connect_test_db(direct_db_path)
    try:
        create_doc(conn, 1, "DIRECT-EXECUTION", "# Direct execution\n\n## Outcomes\nShip it.\n", actor_id=1)
        link_execution_document(conn, item_id=2180, project_id=1, slug="DIRECT-EXECUTION", actor_id=1, session_id="blitz-owner")
    finally:
        conn.close()

    assert _run_implementing_gate(direct_db_path, item_id=2180, session_id="blitz-owner") is None
    conn = connect_test_db(direct_db_path)
    try:
        claim = active_strategy_doc_claim(conn, item_id=2180)
        assert claim is not None
        assert claim["strategy_doc_slug"] == "DIRECT-EXECUTION"
    finally:
        conn.close()

    _seed_activation(
        direct_db_path, item_id=2181, workflow_id="blitz", session_id="blitz-contender", lane_role=LANE_WORKER, touch_path="src/blitz_contender.py"
    )
    conn = connect_test_db(direct_db_path)
    try:
        link_execution_document(conn, item_id=2181, project_id=1, slug="DIRECT-EXECUTION", actor_id=1, session_id="blitz-contender")
    finally:
        conn.close()
    conflict = _run_implementing_gate(direct_db_path, item_id=2181, session_id="blitz-contender")
    assert conflict["error_code"] == "GATE_DOC_CLAIM_ACTIVATION_CONFLICT"
    # The refusal names the holder by the reference an operator can act on.
    assert "YOK-2180" in conflict["error"]

    outcome = handle_transition(
        FunctionCallRequest(
            function="lifecycle.transition.execute",
            actor=ActorContext(session_id="blitz-owner", actor_id="1"),
            target=TargetRef(kind="item", item_id=2180, project_id="yoke"),
            payload={"source_status": "refined-idea", "target_status": "cancelled", "reason": "Direct execution cancelled"},
        )
    )
    assert outcome.primary_success is True, outcome.error
    conn = connect_test_db(direct_db_path)
    try:
        assert active_strategy_doc_claim(conn, item_id=2180) is None
        assert list_item_worktrees(conn, 2180, active_only=True) == []
        released = conn.execute(
            "SELECT released_at, release_reason, release_reason_intent FROM work_claims WHERE target_kind='item' AND scope=%s",
            (make_item_target(2180).scope_json(),),
        ).fetchone()
        assert released[0] is not None
        assert str(released[1]) == "released"
        assert str(released[2]) == "item-terminal:cancelled"
    finally:
        conn.close()

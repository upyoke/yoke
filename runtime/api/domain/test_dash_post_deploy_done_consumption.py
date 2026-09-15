"""Dash done consumes current scoped acceptance, not a historical copy pass."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_dash_post_deploy_review_isolation import (
    _insert_dash,
)
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from runtime.api.fixtures.backlog_inserts import insert_qa_run
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)


def _bind_original(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type) "
        "VALUES(1,'browser-control') ON CONFLICT DO NOTHING"
    )
    original_id = _original_requirement(
        conn, item_id=item_id, method_id="browser-inspection"
    )
    conn.execute(
        "UPDATE qa_requirements SET workflow_transition_id=%s WHERE id=%s",
        (ITEM_POSTURE_VERIFICATION_TRANSITION, original_id),
    )
    conn.commit()
    return original_id


def _accept_member_qa(conn, *, run_id: str, item_id: int) -> None:
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id=f"qa-{run_id}",
    )
    _complete_case(conn, execution)
    accepted = deployment_qa_stage_status(
        conn,
        run_id=run_id,
        stage_name="member-qa",
        member_item_id=item_id,
    )
    assert accepted["accepted"]
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s",
        (run_id,),
    )
    conn.commit()


def _retarget_run(conn, *, run_id: str, lineage: str, created_at: str) -> None:
    conn.execute(
        "UPDATE deployment_runs SET release_lineage=%s, created_at=%s WHERE id=%s",
        (lineage, created_at, run_id),
    )
    conn.execute(
        "UPDATE deployment_stage_receipts SET observed_release_lineage=%s "
        "WHERE run_id=%s AND stage_name='deploy'",
        (lineage, run_id),
    )
    conn.commit()


def _set_member_verdict(conn, *, run_id: str, verdict: dict) -> None:
    flow_id = f"flow-{run_id}"
    raw = conn.execute(
        "SELECT stages FROM deployment_flows WHERE id=%s",
        (flow_id,),
    ).fetchone()["stages"]
    stages = json.loads(str(raw))
    for stage in stages:
        if stage.get("name") == "member-qa":
            stage["verdict"] = verdict
    conn.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (json.dumps(stages), flow_id),
    )
    conn.commit()


def _transition_done(conn, *, item_id: int, monkeypatch: pytest.MonkeyPatch):
    from runtime.api.domain.test_status_transition_preflight import (
        _isolate_status_effects,
    )

    _isolate_status_effects(monkeypatch)
    actor_id = str(
        conn.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )
    return handle_transition(
        FunctionCallRequest(
            function="lifecycle.transition.execute",
            actor=ActorContext(session_id="dash-session", actor_id=actor_id),
            target=TargetRef(kind="item", item_id=item_id, project_id="yoke"),
            payload={
                "source_status": "reviewing-implementation",
                "target_status": "done",
                "reason": "current scoped acceptance consumed intake",
            },
        )
    )


def test_stale_candidate_pass_does_not_satisfy_current_pending_copy(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id = 2330
    _insert_dash(test_db, item_id=item_id, status="reviewing-implementation")
    original_id = _bind_original(test_db, item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-stale-accepted",
        item_id=item_id,
        requirement_id=original_id,
    )
    _accept_member_qa(test_db, run_id="run-stale-accepted", item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-current-pending",
        item_id=item_id,
        requirement_id=original_id,
    )
    _retarget_run(
        test_db,
        run_id="run-current-pending",
        lineage="d" * 40,
        created_at="2026-09-14T00:10:00Z",
    )
    created = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-current-pending",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    copy_id = int(created["created_requirement_ids"][0])
    insert_qa_run(test_db, qa_requirement_id=copy_id, verdict="fail")
    db_path = str(test_db.info.dsn)
    blocked = evaluate(item_id=item_id, target_status="done", db_path=db_path)
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is False
    original_runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
        (original_id,),
    ).fetchone()[0]
    waived = test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s",
        (original_id,),
    ).fetchone()[0]
    assert int(original_runs) == 0
    assert waived is None


def test_current_scoped_acceptance_lets_done_accept_without_original_run(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id = 2331
    _insert_dash(test_db, item_id=item_id, status="reviewing-implementation")
    original_id = _bind_original(test_db, item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-current-accepted",
        item_id=item_id,
        requirement_id=original_id,
    )
    _accept_member_qa(test_db, run_id="run-current-accepted", item_id=item_id)
    record_dash_evidence(
        test_db,
        item_id=item_id,
        result_summary="Merged the Dash.",
        verification_summary="Focused checks passed.",
        verification_status="passed",
        commit_sha="e" * 40,
        merge_sha="d" * 40,
        touched_files=["ui/dash.js"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="abc1234",
    )
    db_path = str(test_db.info.dsn)
    assert evaluate(item_id=item_id, target_status="done", db_path=db_path) is None
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is True, outcome.error
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    original_runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
        (original_id,),
    ).fetchone()[0]
    waived = test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s",
        (original_id,),
    ).fetchone()[0]
    assert status == "done"
    assert int(original_runs) == 0
    assert waived is None


def test_required_human_pending_blocks_done_after_scoped_cases_pass(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id = 2332
    reviewer = 9340
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (reviewer,),
    )
    _insert_dash(test_db, item_id=item_id, status="reviewing-implementation")
    original_id = _bind_original(test_db, item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-human-pending",
        item_id=item_id,
        requirement_id=original_id,
    )
    _set_member_verdict(
        test_db,
        run_id="run-human-pending",
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-human-pending",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-human-pending",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="qa-human-pending",
    )
    _complete_case(test_db, execution)
    pending = deployment_qa_stage_status(
        test_db,
        run_id="run-human-pending",
        stage_name="member-qa",
        member_item_id=item_id,
    )
    assert not pending["accepted"]
    assert pending["request_id"] is not None
    db_path = str(test_db.info.dsn)
    blocked = evaluate(item_id=item_id, target_status="done", db_path=db_path)
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is False
    original_runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
        (original_id,),
    ).fetchone()[0]
    assert int(original_runs) == 0

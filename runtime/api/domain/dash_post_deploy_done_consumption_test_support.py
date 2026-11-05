# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _original_requirement,
    _seed_selected_requirement_run,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import _complete_case

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
        "INSERT INTO project_capabilities(created_at, project_id,type) VALUES('2026-01-01T00:00:00Z', 1,'browser-control') ON CONFLICT DO NOTHING"
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


def _transition_done(conn, *, item_id: int, monkeypatch: pytest.MonkeyPatch):
    from runtime.api.domain.status_transition_preflight_test_support import (
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
                "source_status": "release",
                "target_status": "done",
                "reason": "current scoped acceptance consumed intake",
                "done_nonce_verified": True,
            },
        )
    )

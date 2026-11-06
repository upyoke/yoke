"""Saved QA completions get release credit by retrying their own command."""

from unittest import mock

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.qa_capture_pending_review_test_support import _seed_pending
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.fixtures.dispatch_actor import register_session_actor
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_resettlement import terminal_replay_allowed
from yoke_core.domain.deployment_qa_run_acceptance import item_qa_acceptance_blockers
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_complete
from yoke_core.domain.handlers.qa_plan_review import handle_plan_review_submit
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution
from yoke_core.domain.qa_plan_nothing_owed import nothing_owed


def _request(execution, function, **payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(
            actor_id=str(execution["actor_id"]), session_id=execution["session_id"]
        ),
        target=TargetRef(kind="item", item_id=execution["deployment_member_item_id"]),
        payload={"execution_id": str(execution["id"]), **payload},
    )


def _prepared(conn):
    run_id, member = "run-retry-credit", 9891
    _seed_run(conn, run_id=run_id, stages=_stages(_plan(conn)), members=(member, 9892))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    actor_id = register_session_actor(conn, "retry-owner")
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id=str(actor_id),
        session_id="retry-owner",
    )
    with mock.patch(
        "runtime.api.domain.deployment_qa_stage_execution_test_support.finish_plan_execution"
    ):
        _complete_case(conn, execution)
    return execution


def _bind(monkeypatch, conn):
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: connect_test_database(conn.info.dbname),
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_runs_lock.RUN_ROW_LOCK_TIMEOUT_MS", 100
    )


def _blocked_call(conn, execution, callback):
    holder = connect_test_database(conn.info.dbname)
    try:
        holder.execute(
            "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE",
            (execution["deployment_run_id"],),
        )
        outcome = callback()
        assert not outcome.primary_success
        assert outcome.error.code == "qa_settlement_pending"
        assert "completion is saved" in outcome.error.message
        assert "Rerun the same command" in outcome.error.message
        current = select_plan_execution(conn, str(execution["id"]), lock=False)
        assert current["state"] == "completed"
        conn.commit()
    finally:
        holder.rollback()
        holder.close()


def test_completion_retry_credits_saved_pass_after_run_lock_contention(
    test_db, monkeypatch
):
    execution = _prepared(test_db)
    _bind(monkeypatch, test_db)
    request = _request(execution, "qa.plan_execution.complete")
    with mock.patch(
        "yoke_core.domain.deployment_run_driver_notice.push_run_scoped_notice"
    ) as notice:
        _blocked_call(
            test_db, execution, lambda: handle_plan_execution_complete(request)
        )
        current = select_plan_execution(test_db, str(execution["id"]), lock=False)
        assert terminal_replay_allowed(test_db, request)
        test_db.commit()
        assert handle_plan_execution_complete(request).primary_success
        assert (
            item_qa_acceptance_blockers(
                test_db,
                run_id=current["deployment_run_id"],
                item_id=current["deployment_member_item_id"],
            )
            == []
        )
        test_db.commit()
        replay = dispatch(request)
        assert replay.success, replay.error
    notice.assert_not_called()


def test_review_submit_retry_credits_saved_verdict_after_run_lock_contention(
    test_db, monkeypatch
):
    execution, bundle, requirement = _seed_pending(test_db, "run-review-credit", "item")
    actor_id = register_session_actor(test_db, execution["session_id"])
    test_db.execute(
        "UPDATE qa_plan_executions SET actor_id=%s WHERE id=%s",
        (actor_id, execution["id"]),
    )
    test_db.commit()
    execution["actor_id"] = actor_id
    _bind(monkeypatch, test_db)
    request = _request(
        execution,
        "qa.plan_review.submit",
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement,
                "verdict": "pass",
                "rationale": "Capture passes.",
            }
        ],
    )
    _blocked_call(test_db, execution, lambda: handle_plan_review_submit(request))
    assert terminal_replay_allowed(test_db, request)
    test_db.commit()
    assert handle_plan_review_submit(request).primary_success
    assert (
        item_qa_acceptance_blockers(
            test_db,
            run_id=execution["deployment_run_id"],
            item_id=execution["deployment_member_item_id"],
        )
        == []
    )
    test_db.commit()
    replay = dispatch(request)
    assert replay.success, replay.error


@pytest.mark.parametrize("command", ["nothing-owed", "close-out"])
def test_command_settles_previously_completed_evidence_inline(
    test_db, monkeypatch, command
):
    execution = _prepared(test_db)
    _bind(monkeypatch, test_db)
    request = _request(execution, "qa.plan_execution.complete")
    _blocked_call(test_db, execution, lambda: handle_plan_execution_complete(request))
    if command == "nothing-owed":
        refusal = nothing_owed(
            test_db,
            roster_size=1,
            deployment_run_id=execution["deployment_run_id"],
            deployment_stage="item-qa",
        )
        assert "re-drive" not in str(refusal)
    else:
        from yoke_core.domain.handlers.done_transition_deploy_reads import (
            handle_run_stage_qa_acceptance,
        )

        response = handle_run_stage_qa_acceptance(
            FunctionCallRequest(
                function="done_transition.run_stage_qa_acceptance",
                actor=request.actor,
                target=request.target,
                payload={"run_id": execution["deployment_run_id"]},
            )
        )
        assert response.primary_success
        assert response.result_payload["blocking"] == []
    assert (
        item_qa_acceptance_blockers(
            test_db,
            run_id=execution["deployment_run_id"],
            item_id=execution["deployment_member_item_id"],
        )
        == []
    )


def test_terminal_replay_does_not_authorize_different_owner(test_db):
    execution = _prepared(test_db)
    request = _request(execution, "qa.plan_execution.complete")
    assert not terminal_replay_allowed(test_db, request)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='completed' WHERE id=%s",
        (execution["id"],),
    )
    test_db.commit()
    assert terminal_replay_allowed(test_db, request)
    other = request.model_copy(
        update={"actor": ActorContext(actor_id="2", session_id="different-owner")}
    )
    assert not terminal_replay_allowed(test_db, other)

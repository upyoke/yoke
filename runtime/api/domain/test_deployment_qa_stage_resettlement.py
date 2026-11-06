"""Saved verdicts return promptly and the driver adopts deferred credit."""

from unittest import mock
from time import monotonic

from yoke_contracts.lock_retry import RETRYABLE_LOCK_CODES

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
    # Terminal replay is an exception for an already closed item.
    conn.execute("UPDATE items SET status='done' WHERE id=%s", (member,))
    conn.commit()
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
            "SELECT id FROM items WHERE id=%s FOR NO KEY UPDATE",
            (execution["deployment_member_item_id"],),
        )
        started = monotonic()
        outcome = callback()
        assert monotonic() - started < 3
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["settlement"] == "deferred"
        assert outcome.result_payload["credited_by"] == "the run driver's next QA check"
        assert "qa_settlement_pending" not in RETRYABLE_LOCK_CODES
        current = select_plan_execution(conn, str(execution["id"]), lock=False)
        assert current["state"] == "completed"
        conn.commit()
    finally:
        holder.rollback()
        holder.close()


def _driver_check(conn, execution):
    from yoke_core.domain.deployment_qa_dispatch_gating import gate_members
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    stage = next(
        s
        for s in pinned_stages(conn, execution["deployment_run_id"])
        if s["name"] == execution["deployment_stage"]
    )
    member = execution["deployment_member_item_id"]
    with mock.patch(
        "yoke_core.domain.deployment_qa_member_acceptance_notice.notify_items_qa_accepted"
    ) as close:
        code, reason = gate_members(
            conn,
            stage,
            run_id=execution["deployment_run_id"],
            members=[member],
            errors={},
            project_id=1,
            target_tier="stage",
            revision="a" * 40,
        )
    assert code == 0, reason
    close.assert_called_once_with(
        conn, run_id=execution["deployment_run_id"], item_ids=(member,)
    )


def test_completion_returns_saved_pass_after_member_lock_contention(
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
        _driver_check(test_db, execution)
        assert (
            item_qa_acceptance_blockers(
                test_db,
                run_id=current["deployment_run_id"],
                item_id=current["deployment_member_item_id"],
            )
            == []
        )
        test_db.commit()
        with mock.patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice.notify_item_qa_accepted"
        ) as close:
            replay = dispatch(request)
            assert replay.success, replay.error
        close.assert_not_called()
    notice.assert_not_called()


def test_review_submit_returns_saved_verdict_after_member_lock_contention(
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
    _driver_check(test_db, execution)
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


def test_closeout_reads_blockers_without_settlement_or_write_locks(
    test_db, monkeypatch
):
    from yoke_core.domain.handlers.done_transition_deploy_reads import (
        handle_run_stage_qa_acceptance,
    )

    execution = _prepared(test_db)
    _bind(monkeypatch, test_db)
    request = _request(execution, "qa.plan_execution.complete")
    _blocked_call(test_db, execution, lambda: handle_plan_execution_complete(request))
    holder = connect_test_database(test_db.info.dbname)
    try:
        holder.execute("SELECT id FROM items WHERE id=%s FOR UPDATE", (9891,))
        holder.execute(
            "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE",
            (execution["deployment_run_id"],),
        )
        started = monotonic()
        response = handle_run_stage_qa_acceptance(
            request.model_copy(
                update={
                    "function": "done_transition.run_stage_qa_acceptance",
                    "payload": {"run_id": execution["deployment_run_id"]},
                }
            )
        )
        assert monotonic() - started < 3
        assert response.primary_success, response.error
        assert response.result_payload["blocking"]
    finally:
        holder.rollback()
        holder.close()


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

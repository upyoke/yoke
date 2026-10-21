"""Exact execution re-entry refuses lost host custody without renewal."""

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    TEST_MACHINE_SETTINGS,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_qa_plan_execution_authority import _materialize_two_cases
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import acquire, release, get_claim
from yoke_core.domain.handlers.qa_plan_execution_reentry import handle_execution_reentry
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    set_plan_machine_lease,
)
from yoke_core.domain.qa_plan_execution_reentry import pause_execution
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def test_exact_reentry_preserves_released_lease_and_waiting_cursor(
    test_db, tmp_path, monkeypatch
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    session = "paused-host-custody"
    seed_qa_session(test_db, session, actor_id=1)
    _materialize_two_cases(test_db, item_id=4401)
    execution = begin_plan_execution(
        test_db,
        item_id=4401,
        transition_id="implemented",
        actor_id="1",
        session_id=session,
    )
    lease = acquire(
        test_db,
        make_qa_admission_target(TEST_MACHINE_SETTINGS["resource_name"]),
        session,
    )
    set_plan_machine_lease(test_db, execution, lease_id=lease.id)
    pause_execution(
        test_db,
        execution,
        phase="checkin",
        cursor=0,
        request_id="lost-host-checkin",
        attempts=[{"outcome": "timeout"}],
    )
    release(test_db, lease.id, "custody-ended")
    ended = get_claim(test_db, lease.id)
    response = handle_execution_reentry(
        FunctionCallRequest(
            function="qa.plan_execution.resume",
            actor=ActorContext(actor_id="1", session_id=session),
            target=TargetRef(kind="item", item_id=4401),
            payload={"execution_id": execution["id"], "transition_id": "implemented"},
        )
    )
    assert not response.primary_success
    assert "no longer active" in response.error.message
    retained = get_claim(test_db, lease.id)
    assert not retained.is_active
    assert retained.last_heartbeat == ended.last_heartbeat
    assert test_db.execute(
        "SELECT state,cursor_ordinal,machine_lease_id FROM qa_plan_executions WHERE id=%s",
        (execution["id"],),
    ).fetchone() == ("waiting", 0, lease.id)


def test_unconfirmed_pre_case_pause_reenters_exact_execution_from_saved_receipt(
    monkeypatch,
):
    from runtime.api.fixtures.pg_testdb import test_database
    from runtime.api.domain.test_qa_plan_execution_fail_closed import ACTOR
    from runtime.api.domain.test_qa_plan_checkin_recovery import _response
    from yoke_core.domain import qa_plan_execution, qa_composed_dispatch
    from yoke_core.domain.handlers import qa_plan_execution as handlers
    from yoke_core.domain.qa_plan_execution_store import plan_execution_view
    from yoke_core.domain.project_identity import render_item_ref

    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4401)
        execution = begin_plan_execution(
            conn,
            item_id=4401,
            transition_id="implemented",
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
        )
        view = plan_execution_view(conn, execution)
        public_ref = render_item_ref(conn, 4401)
        conn.commit()
        network_available = False
        cases = []

        def transport(**kwargs):
            function = kwargs["function_id"]
            if function == "qa.plan_execution.begin":
                return _response(kwargs, result=view)
            request = FunctionCallRequest(
                function=function,
                actor=ACTOR,
                target=TargetRef(kind="item", item_id=4401),
                payload=kwargs["payload"],
            )
            if function == "qa.plan_execution.heartbeat" and not network_available:
                # Commit the original liveness write but lose its response.
                outcome = handlers.handle_plan_execution_heartbeat(request)
                assert outcome.primary_success, outcome.error
                return _response(kwargs, code="https_transport_failed")
            if function == "qa.plan_execution.pause" and not network_available:
                return _response(kwargs, code="https_transport_failed")
            handler = {
                "qa.plan_execution.heartbeat": handlers.handle_plan_execution_heartbeat,
                "qa.plan_execution.pause": handle_execution_reentry,
                "qa.plan_execution.resume": handle_execution_reentry,
                "qa.plan_execution.advance": handlers.handle_plan_execution_advance,
                "qa.plan_execution.complete": handlers.handle_plan_execution_complete,
            }.get(function)
            if handler is None:
                assert function == "qa.plan_review.begin"
                return _response(kwargs)
            outcome = handler(request)
            assert outcome.primary_success, outcome.error
            return _response(kwargs, result=outcome.result_payload)

        monkeypatch.setattr(qa_composed_dispatch, "call_qa_function", transport)
        monkeypatch.setattr(
            "yoke_core.domain.qa_plan_execution_checkin.time.sleep", lambda _: None
        )
        monkeypatch.setattr(
            "yoke_core.domain.qa_case_execution.execute_case_context",
            lambda case, **kw: (
                cases.append(case["requirement_id"])
                or {"requirement_id": case["requirement_id"], "verdict": "pass"}
            ),
        )
        paused = qa_plan_execution.execute_plan(
            public_ref=public_ref, transition_id="implemented", actor=ACTOR
        )
        assert paused["state"] == "outcome_unknown"
        assert paused["pause"] == "unconfirmed"
        assert cases == []
        network_available = True
        resumed = qa_plan_execution.execute_plan(
            public_ref=public_ref,
            transition_id="implemented",
            actor=ACTOR,
            resume_execution_id=execution["id"],
            recovery_file=paused["communication"]["evidence_path"],
        )
        assert resumed["state"] == "passed"
        assert resumed["execution_id"] == execution["id"]
        assert len(cases) == len(set(cases)) == 2
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 1
        )
        conn.rollback()


def test_review_wait_reenters_after_heartbeats_while_inflight_case_refuses():
    from runtime.api.fixtures.pg_testdb import test_database
    from runtime.api.domain.test_qa_plan_execution_fail_closed import ACTOR
    from yoke_core.domain.handlers.qa_plan_execution import (
        handle_plan_execution_heartbeat,
    )

    def call(function, execution_id, **payload):
        return FunctionCallRequest(
            function=function,
            actor=ACTOR,
            target=TargetRef(kind="item", item_id=4401),
            payload={"execution_id": execution_id, **payload},
        )

    def resume(execution_id):
        return handle_execution_reentry(
            call("qa.plan_execution.resume", execution_id, transition_id="implemented")
        )

    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4401)
        execution = begin_plan_execution(
            conn,
            item_id=4401,
            transition_id="implemented",
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
        )
        execution_id = execution["id"]
        checked = handle_plan_execution_heartbeat(
            call("qa.plan_execution.heartbeat", execution_id)
        )
        assert checked.primary_success, checked.error
        # A pre-case check-in may have begun its action; re-entry stays refused.
        inflight = resume(execution_id)
        assert not inflight.primary_success
        assert "qa_pause_unconfirmed" in inflight.error.message
        # The capture completed and now waits for review at the roster boundary,
        # still carrying the earlier check-in cursor.
        stale = 'qa-communication-outcome-unknown:{"checkin_cursor":2,"resumed":true}'
        conn.execute(
            "UPDATE qa_plan_executions SET state='awaiting_walk_review',"
            "cursor_ordinal=2,release_reason=%s WHERE id=%s",
            (stale, execution_id),
        )
        conn.commit()
        assert resume(execution_id).primary_success
        conn.execute(
            "UPDATE qa_plan_executions SET release_reason=NULL WHERE id=%s",
            (execution_id,),
        )
        conn.commit()
        for _ in range(2):
            checked = handle_plan_execution_heartbeat(
                call("qa.plan_execution.heartbeat", execution_id)
            )
            assert checked.primary_success, checked.error
            reentered = resume(execution_id)
            assert reentered.primary_success, reentered.error
            assert reentered.result_payload["state"] == "awaiting_walk_review"
        # The boundary heartbeat names no case, so it records no check-in.
        assert (
            conn.execute(
                "SELECT release_reason FROM qa_plan_executions WHERE id=%s",
                (execution_id,),
            ).fetchone()[0]
            is None
        )
        conn.rollback()

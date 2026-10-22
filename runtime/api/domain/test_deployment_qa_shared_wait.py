"""Shared QA contention keeps member custody and wakes the whole stage line."""

import json
from unittest import mock

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _materialize,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case, _plan
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _project,
    _claim,
    seed_session,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def _begin(conn, member, session, **kwargs):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id=session,
        **kwargs,
    )


def _holders(conn):
    _project(conn)
    for member in MEMBERS:
        session = f"member-{member}"
        seed_session(conn, session)
        _claim(
            conn,
            session_id=session,
            target_kind="item",
            scope_json=json.dumps({"item_id": member}),
        )


def _notices(conn, execution):
    return conn.execute(
        "SELECT r.session_id,m.body FROM session_messages m JOIN session_message_recipients r "
        "ON r.message_id=m.message_id WHERE m.idempotency_key LIKE %s",
        (f"%shared-settled:{execution['id']}:%",),
    ).fetchall()


def test_peer_waits_without_taking_shared_execution_and_reuses_passing_evidence(
    test_db,
):
    _seed(test_db)
    for member in MEMBERS:
        _materialize(test_db, member)
    first = _begin(test_db, MEMBERS[0], "first-owner")
    peer = _begin(test_db, MEMBERS[1], "second-owner")
    assert peer["state"] == "waiting"
    assert peer["shared_execution_wait"] == {
        "execution_id": first["id"],
        "owner_session_id": "first-owner",
        "same_target": True,
    }
    assert "park" in peer["recovery"]
    assert _begin(test_db, MEMBERS[0], "first-owner")["id"] == first["id"]
    _complete_case(test_db, first)
    assert deployment_qa_stage_status(
        test_db,
        run_id=RUN,
        stage_name="item-qa",
        member_item_id=MEMBERS[1],
    )["accepted"]
    assert _begin(test_db, MEMBERS[1], "second-owner")["id"] == first["id"]
    assert (
        select_plan_execution(test_db, first["id"], lock=False)["session_id"]
        == "first-owner"
    )
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 1


def test_other_group_runs_concurrently_in_its_own_session(test_db):
    _seed(test_db)
    other = _plan(test_db, "other-shared")
    for member in MEMBERS:
        _attach(test_db, member, other)
        _materialize(test_db, member)
    first = _begin(test_db, MEMBERS[0], "member-9901")
    second = _begin(test_db, MEMBERS[1], "member-9902", plan="other-shared")
    assert first["state"] == second["state"] == "active"
    assert second["session_id"] == "member-9902"
    assert {row["plan_id"] for row in second["roster"]} == {other}
    assert _begin(test_db, MEMBERS[0], "member-9901")["id"] == first["id"]
    assert _begin(test_db, MEMBERS[1], "member-9902")["id"] == second["id"]


@pytest.mark.parametrize("settlement", ["completed", "aborted", "error"])
def test_held_group_waits_on_durable_membership_and_receives_settlement_wake(
    test_db, settlement
):
    _seed(test_db)
    _holders(test_db)
    other = _plan(test_db, "other-shared")
    for member in MEMBERS:
        _attach(test_db, member, other)
        _materialize(test_db, member)
    first = _begin(test_db, MEMBERS[0], "member-9901")
    waiting = _begin(test_db, MEMBERS[1], "member-9902", plan="release-smoke")
    assert waiting["state"] == "waiting"
    assert waiting["shared_execution_wait"]["execution_id"] == first["id"]
    assert "park" in waiting["recovery"]
    if settlement == "completed":
        _complete_case(test_db, first)
    else:
        finish_plan_execution(
            test_db, first, state=settlement, reason="stop shared walk"
        )
    notices = _notices(test_db, first)
    assert {row["session_id"] for row in notices} == {"member-9901", "member-9902"}
    assert all("Shared group evidence comes from" in row["body"] for row in notices)
    assert all("--item YOK-" in row["body"] for row in notices)
    if settlement == "completed":
        # The passed group owes nothing: no replay, and the refusal names the
        # other group's case still waiting for its run.
        from yoke_core.domain.qa_plan_nothing_owed import QaPlanNothingOwed

        with pytest.raises(QaPlanNothingOwed, match="latest verdict is missing"):
            _begin(test_db, MEMBERS[1], "member-9902", plan="release-smoke")
        test_db.rollback()
        second = _begin(test_db, MEMBERS[1], "member-9902")
        assert {row["plan_id"] for row in second["roster"]} == {other}
    else:
        second = _begin(test_db, MEMBERS[1], "member-9902", plan="release-smoke")
    assert second["state"] == "active"
    assert second["session_id"] == "member-9902"


def test_client_returns_shared_wait_before_execution_validation_or_host_work():
    from yoke_core.domain.qa_plan_execution import execute_plan
    from yoke_contracts.api.function_call import ActorContext

    wait = {
        "state": "waiting",
        "shared_execution_wait": {"execution_id": "owned", "owner_session_id": "other"},
    }
    with (
        mock.patch(
            "yoke_core.domain.qa_plan_execution._call_plan_function",
            side_effect=[{}, wait],
        ) as call,
        mock.patch(
            "yoke_core.domain.qa_plan_execution.validate_begun_execution"
        ) as validate,
    ):
        result = execute_plan(
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member="YOK-9902",
            project="yoke",
            actor=ActorContext(actor_id="2", session_id="peer"),
        )
    assert result["state"] == "waiting"
    assert result["executed_count"] == 0
    assert call.call_count == 2
    validate.assert_not_called()


def test_registered_begin_preserves_wait_contract(test_db):
    from uuid import uuid4
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_begin
    from yoke_core.domain.handlers.qa_plan_execution_models import (
        PlanExecutionBeginResponse,
    )

    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    first = _begin(test_db, MEMBERS[0], "first-owner")
    request = FunctionCallRequest(
        function="qa.plan_execution.begin",
        request_id=str(uuid4()),
        target=TargetRef(kind="deployment_run", deployment_run_id=RUN),
        actor=ActorContext(actor_id="2", session_id="peer"),
        payload={"deployment_stage": "item-qa", "deployment_member": "YOK-9902"},
    )
    with (
        mock.patch("yoke_core.domain.db_helpers.connect", return_value=test_db),
        mock.patch.object(test_db, "close"),
    ):
        outcome = handle_plan_execution_begin(request)
    assert outcome.primary_success
    result = PlanExecutionBeginResponse.model_validate(
        outcome.result_payload
    ).model_dump()
    assert result["shared_execution_wait"]["execution_id"] == first["id"]
    assert result["state"] == "waiting"


def test_settlement_wake_names_each_member_s_real_blocker(test_db):
    _seed(test_db)
    _holders(test_db)
    for member in MEMBERS:
        _materialize(test_db, member)
    first = _begin(test_db, MEMBERS[0], "member-9901")
    finish_plan_execution(test_db, first, state="aborted", reason="stop shared walk")

    notices = _notices(test_db, first)
    assert notices
    for row in notices:
        assert (
            f"shared execution {first['id']} settled aborted; member YOK-"
            in (row["body"])
        )
        assert "latest verdict is missing" in row["body"]
        assert "yoke qa plan run --item" in row["body"]


@pytest.mark.parametrize("settlement", ["completed", "aborted", "error"])
def test_unavailable_wake_read_preserves_committed_settlement(
    test_db, capsys, settlement
):
    _seed(test_db)
    for member in MEMBERS:
        _materialize(test_db, member)
    execution = _begin(test_db, MEMBERS[0], "first-owner")
    with mock.patch(
        "yoke_core.domain.deployment_qa_stage_outstanding.qa_stage_outstanding",
        return_value=None,
    ):
        if settlement == "completed":
            _complete_case(test_db, execution)
        else:
            finish_plan_execution(
                test_db, execution, state=settlement, reason="stop shared walk"
            )
    test_db.rollback()
    assert (
        select_plan_execution(test_db, execution["id"], lock=False)["state"]
        == settlement
    )
    warning = capsys.readouterr().out
    assert "shared_qa_wake_unavailable" in warning
    assert f"yoke deployment-runs get {RUN}" in warning
    assert "re-drive its QA stage through the control-plane operator" in warning


def test_abort_cli_succeeds_after_committed_abort_with_unavailable_wake(
    test_db, capsys
):
    from uuid import uuid4
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers import qa_plan_execution as handlers
    from yoke_core.domain import qa_plan_execution_abort_cli as cli

    _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    execution = _begin(test_db, MEMBERS[0], "first-owner")
    actor = ActorContext(actor_id="2", session_id="first-owner")

    def call_abort(**kwargs):
        outcome = handlers.handle_plan_execution_abort(
            FunctionCallRequest(
                function=kwargs["function_id"],
                request_id=str(uuid4()),
                target=TargetRef(kind="deployment_run", deployment_run_id=RUN),
                actor=actor,
                payload=kwargs["payload"],
            )
        )
        assert outcome.primary_success, outcome
        return outcome.result_payload

    with (
        mock.patch.object(
            handlers, "_owned_execution", return_value=(test_db, execution)
        ),
        mock.patch.object(test_db, "close"),
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_outstanding.qa_stage_outstanding",
            return_value=None,
        ),
        mock.patch.object(cli, "_call_plan_function", side_effect=call_abort),
        mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.build_actor",
            return_value=actor,
        ),
    ):
        code = cli.run(
            [
                "--execution-id",
                execution["id"],
                "--reason",
                "operator-interrupt",
                "--project",
                "yoke",
            ]
        )
    assert code == 0
    output = capsys.readouterr().out
    assert "shared_qa_wake_unavailable" in output
    assert json.loads(output.splitlines()[-1])["state"] == "aborted"
    test_db.rollback()
    assert (
        select_plan_execution(test_db, execution["id"], lock=False)["state"]
        == "aborted"
    )

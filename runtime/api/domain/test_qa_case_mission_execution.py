"""A case-selected mission keeps the plan lifecycle and leaves siblings alone."""

from unittest.mock import Mock

import pytest

from runtime.api.domain.test_qa_plan_execution_authority import _materialize_two_cases
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_case_execution as cases
from yoke_core.domain import qa_case_mission_execution as missions
from yoke_core.domain import qa_plan_execution as plans
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
    select_plan_execution,
)


MEMBER_ID = 7
MEMBER_REF = f"EX-{MEMBER_ID}"


def mission_case(**overrides):
    return {
        "requirement_id": 51,
        "runner_id": "agent_mission",
        "project": "example",
        "public_ref": MEMBER_REF,
        "workflow_transition_id": "reviewing-implementation",
        "starting_state": "as_is",
        **overrides,
    }


@pytest.mark.parametrize("deployment", [False, True])
def test_case_routes_exact_mission_into_plan_execution(monkeypatch, deployment):
    case = mission_case()
    if deployment:
        case.update(
            deployment_run_id="release-run",
            deployment_stage="item-qa",
            deployment_member_ref=MEMBER_REF,
            deployment_member_item_id=7,
        )
    monkeypatch.setattr(cases, "fetch_case_execution_context", lambda *a, **k: case)
    expected = {"execution_id": "single-mission", "state": "awaiting_agent_review"}
    execute = Mock(return_value=expected)
    monkeypatch.setattr(missions, "execute_plan", execute)
    assert cases.execute_case(51, base_url="https://example.test") == expected
    selected = execute.call_args.kwargs
    assert selected["requirement_id"] == 51
    assert selected["base_url"] == "https://example.test"
    if deployment:
        assert selected["deployment_member"] == MEMBER_REF
        assert selected["deployment_stage"] == "item-qa"
    else:
        assert selected["public_ref"] == MEMBER_REF


def test_inherit_refuses_before_starting_an_execution(monkeypatch):
    execute = Mock()
    monkeypatch.setattr(missions, "execute_plan", execute)
    with pytest.raises(cases.QaCaseExecutionError, match="qa_single_mission_inherits"):
        missions.execute_mission_case(mission_case(starting_state="inherit"))
    execute.assert_not_called()


def test_single_roster_is_durable_and_other_requirements_are_unchanged():
    with test_database() as conn:
        first, selected = _materialize_two_cases(conn, item_id=4801)
        before = conn.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (first,)
        ).fetchone()
        before = dict(before)
        execution = begin_plan_execution(
            conn,
            item_id=4801,
            transition_id="implemented",
            requirement_id=selected,
            actor_id="7",
            session_id="single-case-owner",
        )
        assert [r["requirement_id"] for r in execution["roster"]] == [selected]
        assert execution["roster"][0]["ordinal"] == 0
        resumed = begin_plan_execution(
            conn,
            item_id=4801,
            transition_id="implemented",
            requirement_id=selected,
            actor_id="7",
            session_id="single-case-owner",
        )
        assert resumed["id"] == execution["id"]
        assert (
            conn.execute(
                "SELECT * FROM qa_requirements WHERE id=%s", (first,)
            ).fetchone()
            == before
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM qa_runs WHERE qa_requirement_id=%s", (first,)
            ).fetchone()[0]
            == 0
        )


def test_existing_whole_roster_is_preserved_when_single_case_cannot_start():
    with test_database() as conn:
        first, selected = _materialize_two_cases(conn, item_id=4802)
        execution = begin_plan_execution(
            conn,
            item_id=4802,
            transition_id="implemented",
            actor_id="7",
            session_id="whole-plan-owner",
        )
        with pytest.raises(
            QaPlanExecutionStateError, match="qa_single_case_scope_busy"
        ):
            begin_plan_execution(
                conn,
                item_id=4802,
                transition_id="implemented",
                requirement_id=selected,
                actor_id="7",
                session_id="whole-plan-owner",
            )
        stored = select_plan_execution(conn, execution["id"], lock=False)
        assert stored["state"] == "active"
        assert [r["requirement_id"] for r in stored["roster"]] == [first, selected]


def test_client_never_materializes_or_runs_siblings_from_an_invalid_reply(monkeypatch):
    call = Mock(
        return_value={
            "execution_id": "wrong-roster",
            "requirements": [{"requirement_id": 51}, {"requirement_id": 52}],
            "state": "active",
        }
    )
    monkeypatch.setattr(plans, "_call_plan_function", call)
    with pytest.raises(
        plans.QaPlanExecutionError, match="qa_single_case_scope_mismatch"
    ):
        plans.execute_plan(
            deployment_run_id="release-run",
            deployment_stage="item-qa",
            deployment_member=MEMBER_REF,
            project="example",
            requirement_id=51,
        )
    assert [c.kwargs["function_id"] for c in call.call_args_list] == [
        "qa.plan_execution.begin"
    ]
    assert call.call_args.kwargs["payload"]["requirement_id"] == 51


def test_single_mission_reaches_review_and_verdict_with_sibling_untouched(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.test_agent_mission_qa import (
        ACTOR,
        _materialize_mission,
        _request,
    )
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.machine_qa_test_support import FakeHostControl
    from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
    from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
    from yoke_core.domain.host_control_runner import (
        clear_host_control_factory,
        register_host_control_factory,
    )
    from yoke_core.domain.machine_qa_local_execution import (
        prepare_agent_mission_contract,
    )
    from yoke_core.domain.qa_plan_review import begin_plan_review
    from yoke_core.domain.qa_plan_review_submission import submit_plan_review
    from yoke_core.domain.qa_plan_attachments import (
        attach_plan_to_item,
        materialize_for_item,
    )
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
    from yoke_core.domain.coordination_claims import get_claim

    item_id = 4803
    configure_test_machine(test_db, tmp_path, monkeypatch)
    selected = _materialize_mission(test_db, item_id=item_id)
    plan = create_plan(
        test_db, project="yoke", slug="sibling-check", name="Sibling check"
    )
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "sibling",
                "position": 1,
                "method_id": "command",
                "instructions": "Leave untouched.",
                "expected_outcome": "Not run.",
                "method_config": {"command": "false"},
            }
        ],
    )
    attach_plan_to_item(
        test_db,
        plan_id=plan["id"],
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    siblings = materialize_for_item(
        test_db, item_id=item_id, transition_id="reviewing-implementation"
    )["created_requirement_ids"]
    assert len(siblings) == 1
    sibling = siblings[0]
    before = test_db.execute(
        "SELECT * FROM qa_requirements WHERE id=%s", (sibling,)
    ).fetchone()
    before = dict(before)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        requirement_id=selected,
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    assert [r["requirement_id"] for r in execution["roster"]] == [selected]
    request_args = dict(
        item_id=item_id, execution_id=execution["id"], requirement_id=selected
    )
    begun = handle_plan_case_begin(
        _request("test_machine.plan_case.begin", ordinal=0, **request_args)
    )
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    register_host_control_factory(lambda _: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(contract)
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready", ordinal=0, payload=prepared, **request_args
        )
    )
    assert ready.primary_success, ready.error
    current = select_plan_execution(test_db, execution["id"], lock=True)
    bundle = begin_plan_review(test_db, current)
    assert current["state"] == "awaiting_agent_review"
    assert len(bundle["dispatch"]["walker_dispatches"]) == 1
    assert get_claim(test_db, int(contract["lease_id"])).is_active
    result = submit_plan_review(
        test_db,
        current,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": selected,
                "verdict": "pass",
                "rationale": "Mission checked.",
            }
        ],
        reviewer_actor_id=ACTOR.actor_id,
        reviewer_session_id=ACTOR.session_id,
    )
    assert result["state"] == "passed"
    assert not get_claim(test_db, int(contract["lease_id"])).is_active
    assert (
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (sibling,)
        ).fetchone()
        == before
    )
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_runs WHERE qa_requirement_id=%s", (sibling,)
        ).fetchone()[0]
        == 0
    )

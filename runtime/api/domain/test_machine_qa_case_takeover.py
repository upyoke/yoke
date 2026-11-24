"""An issued Machine QA case keeps its target across a release takeover."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.machine_qa_host_test_support import (
    _plan_case,
    configure_test_machine,
    machine_case_request,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain import machine_qa_case_execution as client
from yoke_core.domain.claim_chain_state import record_claim_reason
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.deployment_qa_requirement_target_refresh import rebind_subject
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on
from yoke_core.domain.handlers.machine_qa_case import (
    handle_case_begin,
    handle_case_submit,
)
from yoke_core.domain.handlers.machine_qa_execution_abort import handle_case_abort
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import execute_machine_case_contract
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.qa_host_turns import HOST_TURN_REASON
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_pass_currency import (
    has_current_passing_run,
    recorded_execution_target_digest,
)

MEMBER = takeover.WAITING
CASE_KEY = "path-repair-writes-both-startup-files"


@pytest.fixture
def requirement(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    plan = create_plan(
        test_db,
        project="yoke",
        slug="machine-case-takeover",
        name="Machine case takeover",
        infer_target_environment=False,
    )
    plan_id = int(plan["id"])
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[_plan_case(1, CASE_KEY, "fresh-host")],
    )
    stages = item_qa_stage_definitions(plan_id)
    stages[1]["cases"]["case_keys"] = [CASE_KEY]
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=takeover.OLD,
        project="yoke",
        stages=stages,
        members=(MEMBER,),
        lineage=takeover.OLD_LINEAGE,
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    test_db.commit()
    return takeover._requirement(test_db, takeover.OLD, ITEM_QA_STAGE, MEMBER)


def _begin(requirement):
    outcome = handle_case_begin(machine_case_request(requirement))
    assert outcome.primary_success, outcome.error
    execution = outcome.result_payload["execution"]
    assert execution["cases"][0]["deployment_run_id"] == takeover.OLD
    return execution


def _transfer(conn):
    takeover._seed_new(conn)
    transfer_qa_on(conn, old_id=takeover.OLD, new_id=takeover.NEW, moving={MEMBER})
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s WHERE id=%s",
        (takeover.OLD, takeover.NEW),
    )
    conn.commit()


def _submission(execution):
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        return execute_machine_case_contract(execution).payload
    finally:
        clear_host_control_factory()


def _submit(requirement, payload):
    return handle_case_submit(
        machine_case_request(
            requirement, function="test_machine.case.submit", payload=payload
        )
    )


def _abort(requirement, execution, *, actor=None):
    request = machine_case_request(
        requirement,
        function="test_machine.case.abort",
        payload={
            "lease_id": execution["lease_id"],
            "contract_digest": "the digest has no authority over release",
            "reason": "client_cancelled",
        },
    )
    if actor is not None:
        request = request.model_copy(update={"actor": actor})
    return handle_case_abort(request)


def _stored_target(conn, requirement):
    row = conn.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE id=%s", (requirement,)
    ).fetchone()
    return json.loads(row["execution_target_json"])


def _assert_pass(conn, *, requirement, execution, submitted, frozen, current):
    assert submitted.primary_success, submitted.error
    row = conn.execute(
        "SELECT q.deployment_run_id,r.verdict,r.raw_result FROM qa_runs r "
        "JOIN qa_requirements q ON q.id=r.qa_requirement_id WHERE r.id=%s AND q.id=%s",
        (submitted.result_payload["run_id"], requirement),
    ).fetchone()
    assert row["deployment_run_id"] == takeover.NEW
    assert row["verdict"] == "pass"
    assert recorded_execution_target_digest(row["raw_result"]) == target_digest(frozen)
    assert has_current_passing_run(conn, requirement) is current
    assert not get_claim(conn, execution["lease_id"]).is_active


def test_case_submit_moves_with_its_requirement(test_db, requirement):
    frozen = _stored_target(test_db, requirement)
    execution = _begin(requirement)
    _transfer(test_db)
    submitted = _submit(requirement, _submission(execution))
    _assert_pass(
        test_db,
        requirement=requirement,
        execution=execution,
        submitted=submitted,
        frozen=frozen,
        current=True,
    )


def test_case_abort_releases_after_transfer(test_db, requirement):
    execution = _begin(requirement)
    _transfer(test_db)
    aborted = _abort(requirement, execution)
    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["released"] is True
    assert not get_claim(test_db, execution["lease_id"]).is_active


def _rebind(conn, frozen, *, same_destination):
    target = {
        **frozen,
        "deployment": {
            **frozen["deployment"],
            "run_id": takeover.NEW,
            "release_lineage": takeover.NEW_LINEAGE,
        },
    }
    if not same_destination:
        target["endpoints"] = {
            **target["endpoints"],
            "app_url": "https://new.example.test",
        }
    rebound = rebind_subject(
        conn,
        subject={
            "id": takeover.NEW,
            "stage": {"name": ITEM_QA_STAGE},
            "member_item_id": MEMBER,
        },
        target=target,
    )
    conn.commit()
    return rebound


@pytest.mark.parametrize(
    ("same_destination", "transfer_before_begin"),
    [(True, False), (False, False), (True, True)],
)
def test_rebound_case_records_frozen_evidence_with_destination_based_credit(
    test_db,
    requirement,
    same_destination,
    transfer_before_begin,
):
    frozen = _stored_target(test_db, requirement)
    if transfer_before_begin:
        _transfer(test_db)
    execution = _begin(requirement)
    if not transfer_before_begin:
        _transfer(test_db)
    assert _rebind(test_db, frozen, same_destination=same_destination) == [requirement]
    payload = _submission(execution)
    submitted = _submit(requirement, payload)
    _assert_pass(
        test_db,
        requirement=requirement,
        execution=execution,
        submitted=submitted,
        frozen=frozen,
        current=same_destination,
    )
    replayed = _submit(requirement, payload)
    assert replayed.primary_success, replayed.error
    assert replayed.result_payload["run_id"] == submitted.result_payload["run_id"]


@pytest.mark.parametrize("unrelated_rebind", [False, True])
def test_case_target_change_refuses_submit_but_allows_abort(
    test_db, requirement, unrelated_rebind
):
    execution = _begin(requirement)
    target = _stored_target(test_db, requirement)
    if unrelated_rebind:
        _transfer(test_db)
        assert _rebind(test_db, target, same_destination=True) == [requirement]
    if unrelated_rebind:
        target["deployment"] = {
            **target["deployment"],
            "run_id": takeover.NEW,
            "starting_run_id": takeover.NEW,
        }
    else:
        target["endpoints"] = {
            **target["endpoints"],
            "app_url": "https://edited.example.test",
        }
    test_db.execute(
        "UPDATE qa_requirements SET execution_target_json=%s,execution_target_digest=%s "
        "WHERE id=%s",
        (canonical_target(target), target_digest(target), requirement),
    )
    test_db.commit()

    refused = _submit(requirement, _submission(execution))
    assert not refused.primary_success
    assert "host-control target changed after execution began" in refused.error.message
    assert get_claim(test_db, execution["lease_id"]).is_active
    aborted = _abort(requirement, execution)
    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["released"] is True
    assert not get_claim(test_db, execution["lease_id"]).is_active


def test_case_abort_preserves_a_reserved_plan_turn(test_db, requirement):
    execution = _begin(requirement)
    lease_id = execution["lease_id"]
    reason = HOST_TURN_REASON + "plan-turn:operation:borrowed-contract"
    record_claim_reason(test_db, claim_id=lease_id, reason=reason)
    test_db.commit()

    refused = _abort(requirement, execution)
    assert not refused.primary_success
    assert "qa_case_abort_plan_lease" in refused.error.message
    lease = get_claim(test_db, lease_id)
    assert lease.is_active and lease.reason == reason


@pytest.mark.parametrize(
    "identity", [{"actor_id": "2"}, {"session_id": "foreign-session"}]
)
def test_case_abort_refuses_foreign_identity(test_db, requirement, identity):
    execution = _begin(requirement)
    actor = machine_case_request(requirement).actor.model_copy(update=identity)

    refused = _abort(requirement, execution, actor=actor)
    assert not refused.primary_success
    assert "a different session or actor owns it" in refused.error.message
    assert get_claim(test_db, execution["lease_id"]).is_active


def test_client_names_holder_recovery_when_automatic_abort_fails(monkeypatch):
    calls, cleaned = [], []

    def dispatch(function, *_args, **_kwargs):
        calls.append(function)
        if function == "test_machine.case.begin":
            return {
                "state": "ready",
                "execution": {"lease_id": 17, "contract_digest": "issued"},
            }
        raise client.MachineCaseDispatchError(f"{function} refused")

    monkeypatch.setattr(client, "_dispatch_machine_function", dispatch)
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        lambda _execution: SimpleNamespace(
            payload={}, cleanup_artifacts=lambda: cleaned.append(True)
        ),
    )
    case = {
        "requirement_id": 41,
        "runner_id": "host_control",
        "method_id": "machine-state-check",
        "project": "yoke",
        "method_config": {},
        "entry_surface": None,
        "required_completion": None,
    }

    with pytest.raises(client.MachineCaseDispatchError) as error:
        client.execute_materialized_machine_case(
            case, actor=machine_case_request(41).actor
        )

    assert "test_machine.case.submit refused" in str(error.value)
    assert "yoke claims coordination-claim release --claim-id 17" in str(error.value)
    assert [call.rsplit(".", 1)[-1] for call in calls] == ["begin", "submit", "abort"]
    assert cleaned == [True]

"""The host-turn wake's resume re-freezes a member execution moved by takeover."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.test_qa_mixed_os_case_custody import registered_hosts  # noqa: F401
from runtime.api.domain.test_deployment_qa_execution_refreeze import (
    _order,
    _queued_then_taken_over,
    _redeploy_new,
)
from yoke_core.domain.deployment_qa_execution_refreeze import resume_moved_execution
from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON
from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def _pause(conn, execution_id, phase):
    evidence = {"phase": phase, "cursor": 0, "request_id": "host-turn", "attempts": []}
    conn.execute(
        "UPDATE qa_plan_executions SET release_reason=%s WHERE id=%s",
        (PAUSE_REASON + json.dumps(evidence), execution_id),
    )
    conn.commit()


def _resume(conn, execution_id):
    execution = select_plan_execution(conn, execution_id, lock=False)
    return resume_moved_execution(
        conn,
        execution,
        SimpleNamespace(checkout_path=None, expected_branch=None, test_machine=None),
        SimpleNamespace(actor_id="1", session_id=takeover.DRIVER_SESSION),
    )


def test_resume_re_freezes_a_waiting_member_execution_in_place(test_db, monkeypatch):
    moved = _queued_then_taken_over(test_db, monkeypatch)
    _pause(test_db, moved["id"], "checkin")
    order = _order(test_db, moved["id"])
    _redeploy_new(test_db)

    # No `qa plan materialize` precedes a resume; the resume rebinds the cases.
    resumed = _resume(test_db, moved["id"])

    assert resumed is not None and resumed["id"] == moved["id"]
    assert resumed["state"] == "active"
    deployment = resumed["execution_target"]["deployment"]
    assert deployment["run_id"] == takeover.NEW
    assert deployment["release_lineage"] == takeover.NEW_LINEAGE
    assert deployment["starting_run_id"] == takeover.OLD
    assert _order(test_db, moved["id"]) == order
    reason = json.loads(resumed["release_reason"][len(PAUSE_REASON) :])
    assert reason["resumed"] is True


def test_resume_keeps_the_target_of_a_case_whose_outcome_is_unknown(
    test_db, monkeypatch
):
    moved = _queued_then_taken_over(test_db, monkeypatch)
    _pause(test_db, moved["id"], "case")
    _redeploy_new(test_db)

    assert _resume(test_db, moved["id"]) is None
    kept = select_plan_execution(test_db, moved["id"], lock=False)
    assert kept["execution_target_digest"] == moved["execution_target_digest"]


@pytest.fixture
def waiting_workers(test_db, registered_hosts, monkeypatch):  # noqa: F811
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from runtime.api.domain.test_qa_mixed_os_case_custody import ARM_MAC, WINDOWS, _create_plan
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        ITEM_QA_STAGE,
        item_qa_stage_definitions,
        seed_run_standing_on_qa_stage,
    )
    from yoke_core.domain.coordination_claims import acquire
    from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage
    from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
    from yoke_core.domain.qa_plan_execution_store import build_execution_roster
    from yoke_core.domain.qa_plan_partition_chains import partition_key
    from yoke_core.domain.work_claim_targets import make_item_target, make_qa_admission_target

    slug = "mixed-host-release"
    _create_plan(test_db, slug, ("macos", "windows"), method="machine-state-check")
    plan = test_db.execute("SELECT id FROM qa_plans WHERE slug=%s", (slug,)).fetchone()["id"]
    stages = item_qa_stage_definitions(plan)
    stages[1]["cases"]["case_keys"] = ["macos", "windows"]
    member = takeover.WAITING
    seed_run_standing_on_qa_stage(
        test_db, run_id=takeover.OLD, project="yoke", stages=stages,
        members=(member,), lineage=takeover.OLD_LINEAGE,
    )
    test_db.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=%s",
        (f"flow-{takeover.OLD}", member),
    )
    materialize_deployment_qa_stage(
        test_db, deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE, deployment_member_item_id=member,
    )
    scope = dict(deployment_stage=ITEM_QA_STAGE, deployment_member_item_id=member)
    roster = build_execution_roster(
        test_db, deployment_run_id=takeover.OLD, **scope,
    )
    sessions = {"macos": "mac-walk", "windows": "windows-walk"}
    seed_qa_session(
        test_db, takeover.DRIVER_SESSION, "host-holder", *sessions.values(), messageable=True,
    )
    claim = test_db.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,last_heartbeat) "
        "VALUES (%s,'item',%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING id",
        (takeover.DRIVER_SESSION, make_item_target(member).scope_json()),
    ).fetchone()["id"]
    from yoke_core.domain.project_identity import render_item_ref

    ref = render_item_ref(test_db, member)
    partitions = {sessions[row["case_key"]]: partition_key([row]) for row in roster}
    for session_id, key in partitions.items():
        test_db.execute(
            "INSERT INTO session_messages "
            "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
            "VALUES (%s,1,'Resume','fixture','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (session_id,),
        )
        test_db.execute(
            "INSERT INTO session_launches "
            "(launch_id,requester_actor_id,requester_session_id,project_id,message_id,state,"
            "registered_session_id,idempotency_key,deadline_at,created_at,"
            "requested_surface,selected_surface) "
            "VALUES (%s,1,%s,1,%s,'succeeded',%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,"
            "'codex-cli','codex-cli')",
            (session_id, takeover.DRIVER_SESSION, session_id, session_id,
             f"qa-walk:{ref}:{ITEM_QA_STAGE}:{key}:1"),
        )
    test_db.commit()
    queued = {}
    for platform, host in (("macos", ARM_MAC), ("windows", WINDOWS)):
        session_id = sessions[platform]
        execution = begin_plan_execution(
            test_db, deployment_run_id=takeover.OLD, **scope,
            actor_id="1", session_id=session_id, partition=partitions[session_id],
        )
        requirement = execution["roster"][0]["requirement_id"]
        held = acquire(test_db, make_qa_admission_target(host), "host-holder")
        queued[platform] = (execution, host, held.id, requirement)
        waiting = _worker_call(execution, "test_machine.plan_case.begin", ordinal=0, requirement_id=requirement)
        assert waiting.primary_success, waiting.error
        assert waiting.result_payload["state"] == "waiting"

    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    takeover._take_over(test_db)
    _redeploy_new(test_db)
    return queued, claim


def _worker_request(execution, function, *, session_id=None, **payload):
    from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef

    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id=session_id or execution["session_id"]),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"execution_id": execution["id"], **payload},
    )


def _worker_call(execution, function, **payload):
    from yoke_core.domain.handlers.machine_qa_plan_case import (
        handle_plan_case_begin,
        handle_plan_case_submit,
    )
    from yoke_core.domain.handlers.qa_plan_execution_reentry import handle_execution_reentry
    from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict

    request = _worker_request(execution, function, **payload)
    allowed, code, reason = qa_subject_claim_verdict(request)
    assert allowed, (code, reason)
    return {
        "qa.plan_execution.resume": handle_execution_reentry,
        "test_machine.plan_case.begin": handle_plan_case_begin,
        "test_machine.plan_case.submit": handle_plan_case_submit,
    }[function](request)


def test_assigned_workers_resume_their_preserved_host_turns(test_db, waiting_workers):
    from runtime.api.domain.machine_qa_test_support import FakeHostControl
    from yoke_core.domain.coordination_claims import active_claim, release
    from yoke_core.domain.host_control_runner import (
        clear_host_control_factory,
        register_host_control_factory,
    )
    from yoke_core.domain.machine_qa_local_execution import execute_machine_case_contract
    from yoke_core.domain.qa_host_set_turns import execution_waits
    from yoke_core.domain.work_claim_targets import make_qa_admission_target

    queued, _ = waiting_workers
    assert takeover._take_over(test_db) is None
    for execution, host, held_id, requirement in queued.values():
        execution_id = execution["id"]
        order = _order(test_db, execution_id)
        before = execution_waits(test_db, execution_id)[0]
        release(test_db, held_id, "host ready")
        reservation = active_claim(test_db, make_qa_admission_target(host))
        assert reservation.session_id == execution["session_id"]
        for _ in range(2):
            resumed = _worker_call(execution, "qa.plan_execution.resume")
            assert resumed.primary_success, resumed.error
            assert resumed.result_payload["execution_id"] == execution_id
        after = execution_waits(test_db, execution_id)[0]
        assert (after["id"], after["queued_at"], after["claim_id"]) == (
            before["id"], before["queued_at"], reservation.id,
        )
        assert _order(test_db, execution_id) == order
        current = select_plan_execution(test_db, execution_id, lock=False)
        assert current["execution_target"]["deployment"]["release_lineage"] == takeover.NEW_LINEAGE
        assert [case["requirement_id"] for case in current["roster"]] == [requirement]
        begun = _worker_call(execution, "test_machine.plan_case.begin", ordinal=0, requirement_id=requirement)
        assert begun.primary_success, begun.error
        assert begun.result_payload["state"] == "ready"
        assert begun.result_payload["execution"]["lease_id"] == reservation.id
        register_host_control_factory(lambda _material: FakeHostControl())
        try:
            submission = execute_machine_case_contract(begun.result_payload["execution"])
        finally:
            clear_host_control_factory()
        try:
            submitted = _worker_call(
                execution, "test_machine.plan_case.submit", ordinal=0,
                requirement_id=requirement, **submission.payload,
            )
        finally:
            submission.cleanup_artifacts()
        assert submitted.primary_success, submitted.error
        assert submitted.result_payload["cursor_ordinal"] == 1
        assert test_db.execute(
            "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s",
            (requirement,),
        ).fetchone()["verdict"] == "pass"


@pytest.mark.parametrize("change", ["other-worker", "wrong-member", "expired", "changed-roster", "capture"])
def test_resume_refuses_changed_custody(test_db, waiting_workers, change):
    from yoke_core.domain.handlers.qa_plan_execution_reentry import handle_execution_reentry
    from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict

    queued, claim_id = waiting_workers
    execution, _, _, requirement = queued["macos"]
    request = _worker_request(execution, "qa.plan_execution.resume")
    if change == "other-worker":
        request = request.model_copy(update={"actor": request.actor.model_copy(
            update={"session_id": queued["windows"][0]["session_id"]},
        )})
        assert not qa_subject_claim_verdict(request)[0]
        expected = "qa_execution_owner_mismatch"
    elif change == "wrong-member":
        request.payload["deployment_member"] = "YOK-999999999"
        expected = "qa_resume_subject_mismatch"
    elif change == "expired":
        test_db.execute("UPDATE work_claims SET released_at=CURRENT_TIMESTAMP WHERE id=%s", (claim_id,))
        test_db.commit()
        assert qa_subject_claim_verdict(request)[1] == "qa_walk_delegation_lapsed"
        expected = "qa_walk_delegation_lapsed"
    elif change == "changed-roster":
        test_db.execute("UPDATE qa_requirements SET waived_at=CURRENT_TIMESTAMP WHERE id=%s", (requirement,))
        test_db.commit()
        expected = "qa_partition_unavailable"
    else:
        _pause(test_db, execution["id"], "case")
        expected = "qa_action_outcome_unknown"
    refused = handle_execution_reentry(request)
    assert not refused.primary_success
    assert expected in refused.error.message
    kept = select_plan_execution(test_db, execution["id"], lock=False)
    assert kept["execution_target_digest"] == execution["execution_target_digest"]
    assert kept["roster"] == execution["roster"]

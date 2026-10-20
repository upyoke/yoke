"""Removed missions keep their host for owner-only teardown without reviving their walk."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    acquire,
    get_claim,
)
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import prepare_agent_mission_contract
from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_abort_reason import member_removal_pending
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.work_claim_targets import make_qa_admission_target

ITEM = 7841
RUN = "run-mission-teardown"


@pytest.fixture
def removed_mission(test_db, tmp_path, monkeypatch, request):
    restore_receipt = getattr(request, "param", None)
    restored_before_removal = restore_receipt is True
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement = _materialize_mission(test_db, item_id=ITEM)
    execution = begin_plan_execution(
        test_db,
        item_id=ITEM,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    request = _request(
        "test_machine.plan_case.begin",
        item_id=ITEM,
        execution_id=execution_id,
        requirement_id=requirement,
        ordinal=0,
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    original = begun.result_payload["execution"]
    control = FakeHostControl()
    register_host_control_factory(lambda _material: control)
    try:
        prepared = prepare_agent_mission_contract(original)
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        request.model_copy(
            update={
                "function": "test_machine.mission.ready",
                "payload": {**request.payload, **prepared},
            }
        )
    )
    assert ready.primary_success, ready.error
    current = lock_plan_execution(test_db, execution_id)
    begin_plan_review(test_db, current)
    _seed_run(
        test_db,
        run_id=RUN,
        stages=_stages(_plan(test_db)),
        members=(),
        existing_members=(ITEM,),
    )
    test_db.execute(
        "UPDATE qa_plan_executions SET item_id=NULL,transition_id=NULL,deployment_run_id=%s,deployment_stage='item-qa',"
        "deployment_member_item_id=%s WHERE id=%s",
        (RUN, ITEM, execution_id),
    )
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (ITEM,))
    test_db.commit()
    control.existing_paths.add(mission_scratch_path(execution_id) + "/staged-token")
    if restore_receipt:
        import base64
        import json
        from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add

        outcome = handle_qa_artifact_add(request.model_copy(update={
            "function": "qa.artifact.add",
            "target": TargetRef(kind="qa_requirement", qa_requirement_id=requirement),
            "payload": {
                "run_id": ready.result_payload["result"]["run_id"],
                "artifact_type": "starting_state_restore",
                "filename": "starting-state-restore.json",
                "content_type": "application/json",
                "content_base64": base64.b64encode(json.dumps(
                    {"restored": True, "baseline": "fresh-host"}
                    if restored_before_removal else restore_receipt
                ).encode()).decode(),
            },
        }))
        assert outcome.primary_success, outcome.error
    remove_member_on(test_db, RUN, ITEM, reason="later release")
    test_db.commit()
    # Removal keeps the walk's dirty host until its walk-end teardown.
    assert get_claim(test_db, original["lease_id"]).is_active != restored_before_removal
    current = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    assert current["state"] == ("aborted" if restored_before_removal else "awaiting_agent_review")
    assert member_removal_pending(current) != restored_before_removal
    cleanup = request.model_copy(
        update={
            "function": "test_machine.mission.access",
            "target": TargetRef(
                kind="deployment_run", deployment_run_id=RUN, project_id="yoke"
            ),
            "payload": {
                "execution_id": execution_id,
                "requirement_id": requirement,
                "cleanup": "begin",
                "run_id": ready.result_payload["result"]["run_id"],
            },
        }
    )
    return cleanup, control, original


def test_removed_member_walk_end_clears_staged_secrets_and_restores_start(
    test_db, monkeypatch, removed_mission
):
    from yoke_core.domain import machine_qa_mission_walk
    from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
    from yoke_core.domain.yoke_function_dispatch_qa_claims import (
        qa_subject_claim_verdict,
    )

    request, control, original = removed_mission
    assert qa_subject_claim_verdict(request) == (True, None, None)
    assert resolve_run_qa_subject(test_db, request) == (1, "yoke", ITEM)
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    contract = acquired.result_payload["execution"]
    assert (
        contract["settings"]["resource_name"] == original["settings"]["resource_name"]
    )
    assert contract["lease_id"] == original["lease_id"]
    restored = []

    def restore(name):
        assert not any(
            p.startswith(mission_scratch_path(request.payload["execution_id"]))
            for p in control.existing_paths
        )
        restored.append(name)
        return SimpleNamespace(ok=True, error_code=None, evidence={})

    monkeypatch.setattr(
        machine_qa_mission_walk,
        "_execution",
        lambda c: SimpleNamespace(
            control=control,
            material=SimpleNamespace(secrets={}),
            reach_baseline=restore,
        ),
    )
    result = execute_agent_mission_walk_end(contract)
    assert result["removed"]
    assert result["starting_state_restore"]["restored"]
    assert restored == ["fresh-host"]
    finished = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {
                    **request.payload,
                    "cleanup": "finish",
                    "lease_id": contract["lease_id"],
                    "restore": result["starting_state_restore"],
                }
            }
        )
    )
    assert finished.primary_success, finished.error
    assert not get_claim(test_db, contract["lease_id"]).is_active
    current = lock_plan_execution(test_db, request.payload["execution_id"])
    assert current["state"] == "aborted" and current["machine_lease_id"] is None
    assert current["release_reason"] == "deployment-member-removed"
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_artifacts WHERE qa_run_id=%s "
            "AND artifact_type='starting_state_restore'",
            (request.payload["run_id"],),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("change", ["session", "actor", "run", "requirement", "walk"])
def test_cleanup_refuses_wrong_owner_docket_and_normal_walk(removed_mission, change):
    request, _, _ = removed_mission
    if change in {"session", "actor"}:
        request = request.model_copy(
            update={
                "actor": ActorContext(
                    actor_id="2" if change == "actor" else ACTOR.actor_id,
                    session_id="other-session"
                    if change == "session"
                    else ACTOR.session_id,
                )
            }
        )
    else:
        payload = dict(request.payload)
        if change == "walk":
            payload.pop("cleanup")
            payload.pop("run_id")
        else:
            payload["run_id" if change == "run" else "requirement_id"] += 1
        request = request.model_copy(update={"payload": payload})
    outcome = handle_agent_mission_access(request)
    assert not outcome.primary_success


def test_removed_mission_host_is_held_until_walk_end(removed_mission, test_db):
    request, _, original = removed_mission
    host = original["settings"]["resource_name"]
    with pytest.raises(CoordinationClaimHeldError):
        acquire(
            test_db,
            make_qa_admission_target(host),
            "another-session",
            reason="another execution",
        )
    test_db.rollback()
    execution = lock_plan_execution(test_db, request.payload["execution_id"])
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_walk_end_required"):
        finish_plan_execution(test_db, execution, state="aborted", reason="operator")
    test_db.rollback()
    walk = dict(request.payload)
    walk.pop("cleanup")
    walk.pop("run_id")
    refused = handle_agent_mission_access(request.model_copy(update={"payload": walk}))
    assert "mission_member_removed" in refused.error.message
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    replay = handle_agent_mission_access(request)
    assert replay.primary_success, replay.error
    assert replay.result_payload["execution"]["lease_id"] == original["lease_id"]
    assert get_claim(test_db, original["lease_id"]).is_active


@pytest.mark.parametrize("local_failure", [False, True])
def test_walk_end_always_finishes_its_cleanup_lease(monkeypatch, capsys, local_failure):
    from yoke_core.domain import agent_mission_walk_cli, machine_qa_mission_walk
    from yoke_core.domain import qa_composed_dispatch

    def resolve(parsed, *, prog):
        parsed.cleanup_lease = True
        return {"lease_id": 77}

    def teardown(*args, **kwargs):
        if local_failure:
            raise RuntimeError("private-token")
        return {
            "removed": True,
            "stale_owner_marker_removed": True,
            "starting_state_restore": {"restored": True, "baseline": "fresh-host"},
        }

    sent = []
    monkeypatch.setattr(agent_mission_walk_cli, "resolve_mission_contract", resolve)
    monkeypatch.setattr(
        machine_qa_mission_walk, "execute_agent_mission_walk_end", teardown
    )
    monkeypatch.setattr(
        qa_composed_dispatch,
        "call_qa_function",
        lambda **kw: sent.append(kw) or SimpleNamespace(success=True),
    )
    code = agent_mission_walk_cli.run_end(
        [
            "--deployment-run-id",
            RUN,
            "--execution-id",
            "mission-cleanup",
            "--requirement-id",
            "1",
            "--run-id",
            "2",
        ]
    )
    assert code == (2 if local_failure else 0)
    assert len(sent) == 1
    assert sent[0]["payload"]["cleanup"] == "finish"
    assert sent[0]["payload"]["lease_id"] == 77
    assert (sent[0]["payload"]["restore"] is None) == local_failure
    output = capsys.readouterr()
    assert "private-token" not in output.out + output.err

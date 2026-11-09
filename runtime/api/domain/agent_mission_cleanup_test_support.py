# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _materialize_mission,
    _request,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
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
    setup = getattr(request, "param", "removed")
    restored_before_removal = setup is True
    end_kind = setup if isinstance(setup, str) else "removed"
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
    if restored_before_removal:
        import base64
        import json
        from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add

        outcome = handle_qa_artifact_add(
            request.model_copy(
                update={
                    "function": "qa.artifact.add",
                    "target": TargetRef(
                        kind="qa_requirement", qa_requirement_id=requirement
                    ),
                    "payload": {
                        "run_id": ready.result_payload["result"]["run_id"],
                        "artifact_type": "starting_state_restore",
                        "filename": "starting-state-restore.json",
                        "content_type": "application/json",
                        "content_base64": base64.b64encode(
                            json.dumps(
                                {
                                    "restored": True,
                                    "baseline": "fresh-host",
                                }
                            ).encode()
                        ).decode(),
                    },
                }
            )
        )
        assert outcome.primary_success, outcome.error
    if end_kind == "removed":
        remove_member_on(test_db, RUN, ITEM, reason="later release")
    else:
        from yoke_core.domain.qa_plan_execution_abort_state import record_abort_request
        from yoke_core.domain.qa_deployment_run_settlement import (
            settle_unsuccessful_run,
        )

        current = lock_plan_execution(test_db, execution_id)
        record_abort_request(test_db, current, {"reason": "stop mission", "ordinal": 0})
        test_db.execute(
            "UPDATE deployment_runs SET status=%s WHERE id=%s", (end_kind, RUN)
        )
        settle_unsuccessful_run(test_db, RUN, reason="run ended")
    test_db.commit()
    # Removal keeps the walk's dirty host until its walk-end teardown.
    assert get_claim(test_db, original["lease_id"]).is_active != restored_before_removal
    current = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    assert current["state"] == ("aborted" if restored_before_removal else "walking")
    assert member_removal_pending(current) == (
        end_kind == "removed" and not restored_before_removal
    )
    cleanup = request.model_copy(
        update={
            "function": "test_machine.mission.access",
            "target": TargetRef(kind="global", project_id="yoke"),
            "payload": {
                "execution_id": execution_id,
                "requirement_id": requirement,
                "cleanup": "begin",
                "run_id": ready.result_payload["result"]["run_id"],
            },
        }
    )
    return cleanup, control, original

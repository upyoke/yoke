"""An exact execution resume keeps its required host and queue place."""

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import _environment
from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    _terminal_recipe,
    configure_test_machine,
    verify_fixture_host,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import _notices
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.machine_config.capability_secret_store import store_test_machine_secret
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.handlers.qa_plan_execution_reentry import handle_execution_reentry
from yoke_core.domain.machine_qa_capability import (
    host_claim_target,
    replace_test_machine_settings,
)
from yoke_core.domain.qa_host_set_turns import execution_waits
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution


@pytest.fixture
def queued_host_case(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _notices(monkeypatch)
    lab_a = TEST_MACHINE_SETTINGS["resource_name"]
    lab_b = "mac-mini-lab-2"
    replace_test_machine_settings(
        test_db,
        power_project="yoke",
        test_machine=lab_b,
        settings={**TEST_MACHINE_SETTINGS, "resource_name": lab_b},
        base_settings=None,
    )
    store_test_machine_secret(lab_b, "ssh_private_key", "fixture-key")
    verify_fixture_host(test_db, lab_b)
    actor = ActorContext(actor_id="1", session_id="host-wait-owner")
    seed_qa_session(test_db, actor.session_id, "host-holder")
    _environment(test_db)
    plan = create_plan(
        test_db, project="yoke", slug="host-wait", target_environment="stage"
    )
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[{
            "case_key": "use-host",
            "method_id": "terminal-check",
            "instructions": "Run the terminal check.",
            "expected_outcome": "The check passes.",
            "method_config": {**_terminal_recipe(), "os": "macos"},
            "entry_surface": "printf done",
            "required_completion": "complete",
            "host_baselines": ["fresh-host"],
        }],
    )
    execution = begin_standalone_execution(
        test_db,
        plan="host-wait",
        project="yoke",
        actor_id=actor.actor_id,
        session_id=actor.session_id,
    )
    return lab_a, lab_b, actor, execution


def test_bare_resume_keeps_required_host_and_queue_place(test_db, queued_host_case):
    lab_a, lab_b, actor, execution = queued_host_case
    execution_id = execution["id"]
    target_a = host_claim_target(lab_a)
    holder = acquire(test_db, target_a, "host-holder")
    assert active_claim(test_db, host_claim_target(lab_b)) is None

    def begin(**pin):
        outcome = handle_plan_case_begin(
            FunctionCallRequest(
                function="test_machine.plan_case.begin",
                actor=actor,
                target=TargetRef(kind="global", project_id="yoke"),
                payload={
                    "execution_id": execution_id,
                    "ordinal": 0,
                    "requirement_id": execution["roster"][0]["requirement_id"],
                    **pin,
                },
            )
        )
        assert outcome.primary_success, outcome.error
        return outcome.result_payload

    def resume():
        outcome = handle_execution_reentry(
            FunctionCallRequest(
                function="qa.plan_execution.resume",
                actor=actor,
                target=TargetRef(kind="global"),
                payload={"execution_id": execution_id},
            )
        )
        assert outcome.primary_success, outcome.error

    waiting = begin(test_machine=lab_a)
    assert waiting["state"] == "waiting"
    assert waiting["host_wait"]["resume_command"] == (
        f"yoke qa plan run --resume-execution-id {execution_id}"
    )
    first, = execution_waits(test_db, execution_id)
    assert first["test_machine"] == lab_a and first["need_id"] is None

    resume()
    assert begin()["state"] == "waiting"
    current, = execution_waits(test_db, execution_id)
    assert current["test_machine"] == lab_a
    assert (current["id"], current["queued_at"]) == (first["id"], first["queued_at"])
    assert active_claim(test_db, host_claim_target(lab_b)) is None

    release(test_db, holder.id, "done")
    reserved, = execution_waits(test_db, execution_id)
    assert reserved["id"] == first["id"] and reserved["state"] == "reserved"
    resume()
    ready = begin()
    assert ready["state"] == "ready"
    assert ready["execution"]["settings"]["resource_name"] == lab_a
    assert ready["execution"]["lease_id"] == reserved["claim_id"]
    assert not execution_waits(test_db, execution_id)

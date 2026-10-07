"""Contention discovered by a walker queues fresh QA without a FAIL verdict."""

from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    register_host_control_factory,
    clear_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import prepare_agent_mission_contract
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_host_wait_submission import submit_host_wait


def test_host_wait_preserves_target_and_open_requirement(
    test_db, tmp_path, monkeypatch
):
    from yoke_core.domain.machine_qa_capability import (
        replace_test_machine_settings,
        host_claim_target,
    )
    from yoke_core.domain.coordination_claims import acquire, get_claim
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session

    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, "busy-host-owner")
    replace_test_machine_settings(
        test_db,
        project="yoke",
        machine="linux-lab",
        settings={
            "resource_name": "linux-lab",
            "host": "lab.local",
            "user": "tester",
            "os": "linux",
            "operating_notes": "",
        },
        base_settings=None,
    )
    item_id = 7654
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution["id"],
            requirement_id=requirement_id,
            ordinal=0,
            payload={"machine": "mac-mini-lab"},
        )
    )
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    register_host_control_factory(lambda material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(contract)
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution["id"],
            requirement_id=requirement_id,
            ordinal=0,
            payload=prepared,
        )
    )
    assert ready.primary_success, ready.error
    current = lock_plan_execution(test_db, execution["id"])
    bundle = begin_plan_review(test_db, current)
    busy = acquire(test_db, host_claim_target("linux-lab"), "busy-host-owner")
    result = submit_host_wait(
        test_db,
        current,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        machine="linux-lab",
        rationale=f"host leased by another mission: {busy.id}",
    )
    assert result["state"] == "waiting" and result["verdicts"] == []
    assert get_claim(test_db, contract["lease_id"]).is_active is False
    fresh = lock_plan_execution(test_db, result["execution_id"])
    assert fresh["execution_target_digest"] == current["execution_target_digest"]
    assert fresh["cursor_ordinal"] == 0 and fresh["roster"] == current["roster"]
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s AND verdict IS NOT NULL",
            (requirement_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_plan_review_verdicts WHERE bundle_id=%s",
            (bundle["bundle_id"],),
        ).fetchone()[0]
        == 0
    )

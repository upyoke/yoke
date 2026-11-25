"""A mission walk taken over mid-walk keeps commanding its host and ends cleanly.

Takeover moves a walking item-QA execution onto the successor run but keeps
its frozen target. The successor's item-QA materialization then rebinds the
requirement to its own lineage, keeping the frozen ``starting_run_id``. The
walk's next host command and its walk-end must still read the case as the one
it froze, rather than refusing with "ordered plan case snapshot changed".
"""

from __future__ import annotations

import base64
import json
import subprocess

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.agent_mission_qa_test_support import ACTOR
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_deployment_qa_execution_refreeze import _redeploy_new
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.domain.qa_verdict_citation_test_support import cite_case

from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_agent_mission_host_command,
    prepare_agent_mission_contract,
)
from yoke_core.domain.machine_qa_mission_walk import execute_agent_mission_walk_end
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add
from yoke_core.domain.qa_case_execution_context import (
    QaCaseExecutionError,
    get_case_execution_context,
)
from yoke_core.domain.handlers.qa_plan_review import handle_plan_review_submit
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_execution_stop import STEERING_STOP_REASON, stop_plan_execution
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run

MEMBER = takeover.WAITING
CASE_KEY = "new-user-install"
COMMAND_KEY = "extra-command"


def _mission_plan(conn) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"mission-{takeover.OLD}",
        name="Release mission",
        infer_target_environment=False,
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": CASE_KEY,
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": "Install the deployed release as a new user.",
                "expected_outcome": "Ranked actionable findings.",
                "method_config": {"executor": "informed_subagent", "os": "macos"},
                "host_baselines": ["fresh-host"],
            },
            {
                "case_key": COMMAND_KEY,
                "position": 2,
                "method_id": "command",
                "instructions": "Run an independent command.",
                "expected_outcome": "The command exits successfully.",
                "method_config": {"command": "true"},
            },
        ],
    )
    return int(plan["id"])


def _seed_old_with_mission(conn) -> int:
    """OLD stands on item QA; PASSED closed, WAITING owes the mission."""
    stages = item_qa_stage_definitions(_mission_plan(conn))
    stages[1]["cases"]["case_keys"] = [CASE_KEY, COMMAND_KEY]
    seed_run_standing_on_qa_stage(
        conn,
        run_id=takeover.OLD,
        project="yoke",
        stages=stages,
        members=(takeover.PASSED, MEMBER),
        lineage=takeover.OLD_LINEAGE,
    )
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=%s",
        (f"flow-{takeover.OLD}", MEMBER),
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    requirement = takeover._requirement(conn, takeover.OLD, ITEM_QA_STAGE, MEMBER)
    conn.commit()
    takeover._close_passed(conn)
    return requirement


def _begin_walk(conn, requirement: int) -> FunctionCallRequest:
    """Begin the mission case and mark it ready, as `yoke qa plan run` does."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    request = FunctionCallRequest(
        function="test_machine.plan_case.begin",
        actor=ACTOR,
        target=TargetRef(kind="global", project_id="yoke"),
        payload={
            "execution_id": str(execution["id"]),
            "requirement_id": requirement,
            "ordinal": 0,
        },
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(begun.result_payload["execution"])
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
    current = lock_plan_execution(conn, str(execution["id"]))
    advance_plan_execution(
        conn, current, ordinal=1,
        requirement_id=current["roster"][1]["requirement_id"],
        result={"runner_id": "worktree_run", "verdict": "pass", "case_outcome": "passed"},
        commit=False,
    )
    begin_plan_review(conn, current)
    conn.commit()
    return request.model_copy(
        update={
            "function": "test_machine.mission.access",
            "payload": {
                "execution_id": str(execution["id"]),
                "requirement_id": requirement,
                "run_id": ready.result_payload["result"]["run_id"],
            },
        }
    )


def _requirement_target(conn, requirement: int) -> tuple[dict, str]:
    row = conn.execute(
        "SELECT execution_target_json,execution_target_digest,deployment_run_id "
        "FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone()
    assert row["deployment_run_id"] == takeover.NEW
    return json.loads(row["execution_target_json"]), row["execution_target_digest"]


@pytest.mark.parametrize("waive_mission", [False, True], ids=["review", "steering-abort"])
def test_taken_over_mission_walk_commands_its_host_and_ends(
    test_db, tmp_path, monkeypatch, waive_mission,
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    # Suppress only the external review wake sent to the run's driver session.
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_agent_review_wake.notify_scoped_agent_review",
        lambda *_a, **_k: None,
    )
    requirement = _seed_old_with_mission(test_db)
    access = _begin_walk(test_db, requirement)
    execution_id = access.payload["execution_id"]
    frozen = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    assert frozen["state"] == "walking"
    frozen_digest = test_db.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone()["execution_target_digest"]

    # The real takeover moves the walking execution onto the successor run.
    takeover._seed_new(test_db)
    takeover._contains(monkeypatch)
    assert takeover._take_over(test_db) == takeover.OLD
    moved = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    assert moved["deployment_run_id"] == takeover.NEW
    assert moved["execution_target_digest"] == frozen["execution_target_digest"]
    assert moved["execution_target"]["deployment"]["run_id"] == takeover.OLD

    # The successor deploys, and its item-QA materialization rebinds the case.
    _redeploy_new(test_db)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    test_db.commit()
    target, digest = _requirement_target(test_db, requirement)
    assert digest != frozen_digest
    assert target["deployment"]["run_id"] == takeover.NEW
    assert target["deployment"]["release_lineage"] == takeover.NEW_LINEAGE
    assert target["deployment"]["starting_run_id"] == takeover.OLD

    waived_id = requirement if waive_mission else frozen["roster"][1]["requirement_id"]
    waive_requirement(test_db, waived_id, "Waived during the frozen walk.", force=True)
    with pytest.raises(QaCaseExecutionError, match=rf"requirement {waived_id} is waived"):
        get_case_execution_context(test_db, requirement_id=waived_id)
    test_db.rollback()

    def assert_begin_preserves_walk(state):
        with pytest.raises(QaPlanExecutionStateError, match="^qa_walk_in_progress:") as refusal:
            begin_plan_execution(
                test_db,
                deployment_run_id=takeover.NEW,
                deployment_stage=ITEM_QA_STAGE,
                deployment_member_item_id=MEMBER,
                actor_id=ACTOR.actor_id,
                session_id=ACTOR.session_id,
            )
        message = str(refusal.value)
        assert "yoke qa mission walk-end" in message
        assert "yoke qa plan review-submit" in message
        assert "yoke qa plan abort" not in message
        still = lock_plan_execution(test_db, execution_id)
        test_db.rollback()
        assert still["state"] == state
        assert still["execution_target_digest"] == frozen["execution_target_digest"]

    assert_begin_preserves_walk("walking")
    # A mission host command is granted and runs on the walk's own lease.
    command = handle_agent_mission_access(access)
    assert command.primary_success, command.error
    contract = command.result_payload["execution"]
    assert contract["lease_id"] == frozen["test_machine_lease_id"]

    class CommandControl(FakeHostControl):
        def run_command(self, argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "walked", "")

    register_host_control_factory(lambda _material: CommandControl())
    try:
        result = execute_agent_mission_host_command(
            contract, argv=["hostname"], gui_session=False, timeout_seconds=60
        )
    finally:
        clear_host_control_factory()
    assert result["exit_code"] == 0
    assert result["stdout"] == "walked"

    # Walk-end resolves the same contract, then tears down and restores.
    ending = handle_agent_mission_access(access)
    assert ending.primary_success, ending.error
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        ended = execute_agent_mission_walk_end(ending.result_payload["execution"])
    finally:
        clear_host_control_factory()
    assert ended["removed"]
    assert ended["starting_state_restore"]["restored"] is True
    assert ended["starting_state_restore"]["baseline"] == "fresh-host"

    run_id = access.payload["run_id"]
    saved = handle_qa_artifact_add(FunctionCallRequest(
        function="qa.artifact.add", actor=ACTOR,
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement),
        payload={
            "run_id": run_id, "artifact_type": "starting_state_restore",
            "filename": "starting-state-restore.json", "content_type": "application/json",
            "content_base64": base64.b64encode(json.dumps(ended["starting_state_restore"]).encode()).decode(),
        },
    ))
    assert saved.primary_success, saved.error
    assert test_db.execute(
        "SELECT id FROM qa_artifacts WHERE qa_run_id=%s AND artifact_type='starting_state_restore'",
        (run_id,),
    ).fetchone()["id"] == saved.result_payload["qa_artifact_id"]
    assert_begin_preserves_walk("awaiting_walk_review")

    current = lock_plan_execution(test_db, execution_id)
    if waive_mission:
        stopped = stop_plan_execution(
            test_db, current, actor_id="9", session_id="steering-session", reason="stop after restore",
        )
        assert stopped["state"] == "aborted"
        assert stopped["release_reason"].startswith(STEERING_STOP_REASON)
        assert not get_claim(test_db, contract["lease_id"]).is_active
    else:
        bundle = begin_plan_review(test_db, current)
        test_db.commit()
        submitted = handle_plan_review_submit(FunctionCallRequest(
            function="qa.plan_review.submit", actor=ACTOR,
            target=TargetRef(kind="item", item_id=MEMBER),
            payload={
                "execution_id": execution_id, "bundle_id": bundle["bundle_id"],
                "bundle_digest": bundle["bundle_digest"],
                "verdicts": [{
                    "requirement_id": requirement, "verdict": "pass",
                    "rationale": cite_case(bundle, "The walk finished on the retained host."),
                }],
            },
        ))
        assert submitted.primary_success, submitted.error
        assert submitted.result_payload["state"] == "passed"
        assert has_current_passing_run(test_db, requirement)
        assert test_db.execute(
            "SELECT rebound_from_digest FROM qa_requirements WHERE id=%s", (requirement,)
        ).fetchone()["rebound_from_digest"] == frozen["execution_target_digest"]

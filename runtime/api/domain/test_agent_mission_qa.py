"""Main-owned exploratory mission execution and review contracts."""

from __future__ import annotations

import subprocess
from typing import Any

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.machine_qa_execution import (
    AGENT_MISSION_ARTIFACT_LIMIT,
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
)
from yoke_core.domain.agent_mission_recording import (
    handle_agent_mission_access,
    handle_agent_mission_ready,
)
from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract
from yoke_core.domain.coordination_leases import get_lease
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_agent_mission_host_command,
    prepare_agent_mission_contract,
)
from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.schema_init_tables import create_governed_tables


ACTOR = ActorContext(actor_id="2", session_id="session-agent-mission")


class _CommandHostControl(FakeHostControl):
    def __init__(self) -> None:
        super().__init__()
        self.session_contexts: list[str | None] = []

    def run_command(
        self,
        argv: list[str],
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        self.session_contexts.append(required_session_context)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=1,
            stdout="",
            stderr="OAuth session expired and unrefreshable",
        )


def _request(
    function: str,
    *,
    item_id: int,
    execution_id: str,
    requirement_id: int,
    ordinal: int | None = None,
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ACTOR,
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "execution_id": execution_id,
            "requirement_id": requirement_id,
            **({"ordinal": ordinal} if ordinal is not None else {}),
            **(payload or {}),
        },
    )


def _materialize_mission(conn: Any, *, item_id: int) -> int:
    create_governed_tables(conn)
    sync_machine_qa_pack_methods(conn)
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type) "
        "VALUES(1,'browser-control')"
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"exploratory-mission-{item_id}",
        name="Exploratory mission",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "new-user-install",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": (
                    "Install as a new user and investigate onboarding gaps "
                    "using the terminal, browser, and visible desktop."
                ),
                "expected_outcome": (
                    "Return ranked actionable findings and name anything "
                    "that could not be checked."
                ),
                "method_config": {"executor": "naive_target_session"},
                "host_baselines": ["fresh-host"],
            }
        ],
    )
    insert_item(
        conn,
        id=item_id,
        title="Explore new-user installation",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        conn,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    return int(materialized["created_requirement_ids"][0])


def test_mission_parks_resumes_and_persists_the_main_report(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4550
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    assert execution["roster"][0]["required_capability_kinds"] == [
        "browser-control",
        "test-machine",
    ]
    begun = handle_plan_case_begin(
        _request(
            "test_machine.plan_case.begin",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
        )
    )
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    lease_id = int(contract["lease_id"])
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(contract)
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload=prepared,
        )
    )
    assert ready.primary_success, ready.error
    refused_replay = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            item_id=item_id,
            execution_id=execution_id,
            ordinal=0,
            requirement_id=requirement_id,
            payload={**prepared, "contract_digest": "tampered"},
        )
    )
    assert not refused_replay.primary_success
    assert refused_replay.error.code == "agent_mission_ready_failed"
    current = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, current)

    assert bundle is not None
    assert current["state"] == "awaiting_agent_review"
    assert current["machine_lease_id"] == lease_id
    assert get_lease(test_db, lease_id).is_active is True
    dispatch = bundle["dispatch"]
    assert dispatch["dispatch_kind"] == "main_agent_mission"
    assert dispatch["artifact_limit"] == AGENT_MISSION_ARTIFACT_LIMIT
    walker = dispatch["walker_dispatches"][0]
    assert walker["dispatch_kind"] == "target_machine_agent_session"
    assert walker["subagent_type"] is None
    assert "yoke qa browser setup" in walker["browser_setup_command"]
    assert "yoke qa browser step" in walker["browser_step_command"]
    assert f"--run-id {ready.result_payload['result']['run_id']}" in (
        walker["artifact_add_command"]
    )
    assert "WALK_STATUS: HUMAN_GATE" in walker["prompt"]

    command_control = _CommandHostControl()
    register_host_control_factory(lambda _material: command_control)
    try:
        ssh_result = execute_agent_mission_host_command(
            contract,
            argv=["credential", "status"],
            gui_session=False,
            timeout_seconds=60,
        )
        gui_result = execute_agent_mission_host_command(
            contract,
            argv=["credential", "status"],
            gui_session=True,
            timeout_seconds=60,
        )
    finally:
        clear_host_control_factory()
    assert ssh_result["session_context_error_code"] == (
        "macos_login_keychain_context_unavailable"
    )
    assert gui_result["session_context_error_code"] is None
    assert command_control.session_contexts == [None, "gui"]

    resumed = handle_agent_mission_access(
        _request(
            "test_machine.mission.access",
            item_id=item_id,
            execution_id=execution_id,
            requirement_id=requirement_id,
        )
    )
    assert resumed.primary_success, resumed.error
    assert int(resumed.result_payload["execution"]["lease_id"]) == lease_id

    rationale = (
        "Ranked findings: 1. Onboarding completed without a blocker. "
        "No important area remained unverified."
    )
    result = submit_plan_review(
        test_db,
        current,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": "pass",
                "rationale": rationale,
            }
        ],
        reviewer_actor_id=ACTOR.actor_id,
        reviewer_session_id=ACTOR.session_id,
    )
    assert result["state"] == "passed"
    assert get_lease(test_db, lease_id).is_active is False
    final = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs "
        "WHERE qa_requirement_id=%s AND performed_by='agent'",
        (requirement_id,),
    ).fetchone()
    assert tuple(final) == ("pass", rationale)


def test_mixed_bundle_keeps_all_final_verdicts_with_the_main_owner() -> None:
    bundle = {
        "bundle_id": "bundle-1",
        "bundle_digest": "a" * 64,
        "execution_id": "execution-1",
        "execution_target": {"environment": {"name": "preview"}},
        "execution_target_digest": "b" * 64,
        "subject": {"item_id": 42, "deployment_run_id": None},
        "cases": [
            {
                "requirement_id": 1,
                "capture_runner": "agent_mission",
                "capture_run_id": 10,
                "executor": "informed_subagent",
                "instructions": "Explore the onboarding flow.",
                "expected_outcome": "Return ranked findings.",
                "artifacts": [],
                (
                    "transcript"
                ): {
                    "preparation": {
                        "ok": False,
                        "error_code": TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
                    }
                },
            },
            {
                "requirement_id": 2,
                "capture_runner": "host_control",
                "artifacts": [{"id": 20}],
            },
        ],
    }

    dispatch = agent_mission_dispatch_contract(bundle)

    assert dispatch["main_review_requirement_ids"] == [2]
    assert len(dispatch["walker_dispatches"]) == 1
    assert "each of the 2 bundle cases" in dispatch["prompt"]
    assert dispatch["result_schema"]["verdicts"][0]["verdict"] == (
        "pass|fail|undetermined"
    )
    assert TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE in dispatch["prompt"]
    assert "Privacy & Security" in dispatch["prompt"]
    walker_prompt = dispatch["walker_dispatches"][0]["prompt"]
    assert TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE in walker_prompt

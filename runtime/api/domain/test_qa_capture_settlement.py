"""Reviewed and terminated QA executions leave no capture run unsettled.

Whatever ends an exploratory mission's execution — an agent verdict or an
operator abort — must settle its NULL-verdict capture run in place, or every
terminal item transition refuses while the gate summary reports green.
"""

from __future__ import annotations

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
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    prepare_agent_mission_contract,
)
from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_terminal_settlement import find_unsettled_records
from yoke_core.domain.schema_init_tables import create_governed_tables


ACTOR = ActorContext(actor_id="2", session_id="settlement-session")


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
    """One materialized exploratory-mission requirement; returns its id."""
    create_governed_tables(conn)
    sync_machine_qa_pack_methods(conn)
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type) VALUES(1,'browser-control')"
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"mission-settlement-{item_id}",
        name="Mission settlement",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "explore-onboarding",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": "Investigate onboarding gaps.",
                "expected_outcome": "Return ranked findings.",
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


def _capture_attempt(
    test_db: Any,
    *,
    item_id: int,
    requirement_id: int,
) -> str:
    """Begin an execution and land its docket capture; returns execution id."""
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
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
    return execution_id


def _unsettled_run_ids(conn: Any, requirement_id: int) -> list[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s "
            "AND verdict IS NULL ORDER BY id",
            (requirement_id,),
        ).fetchall()
    ]


def _submit_pass(
    conn: Any,
    execution: Any,
    bundle: Any,
    requirement_id: int,
    rationale: str,
) -> dict[str, Any]:
    return submit_plan_review(
        conn,
        execution,
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


def test_review_submission_settles_the_capture_run_in_place(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4601
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db,
        item_id=item_id,
        requirement_id=requirement_id,
    )
    execution = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, execution)
    assert bundle is not None
    capture_run_id = bundle["cases"][0]["capture_run_id"]
    assert _unsettled_run_ids(test_db, requirement_id) == [capture_run_id]

    result = _submit_pass(
        test_db,
        execution,
        bundle,
        requirement_id,
        "Ranked findings cover the expected outcome.",
    )

    assert result["state"] == "passed"
    assert _unsettled_run_ids(test_db, requirement_id) == []
    capture_row = test_db.execute(
        "SELECT verdict,verdict_reason,execution_status,case_outcome "
        "FROM qa_runs WHERE id=%s",
        (capture_run_id,),
    ).fetchone()
    assert capture_row["verdict"] == "pass"
    assert capture_row["verdict_reason"] == (
        "Ranked findings cover the expected outcome."
    )
    # Browser-evidence gates match reviewed captures on these two columns
    # plus the linked verdict; settlement must not disturb either.
    assert capture_row["execution_status"] == "captured"
    assert capture_row["case_outcome"] == "needs_review"

    # A replayed submission settles nothing new and unsettles nothing old.
    replay = _submit_pass(
        test_db,
        execution,
        bundle,
        requirement_id,
        "Ranked findings cover the expected outcome.",
    )
    assert replay["state"] == "passed"
    assert len(replay["verdicts"]) == 1
    assert _unsettled_run_ids(test_db, requirement_id) == []


def test_aborted_execution_settles_its_unreviewed_capture(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4602
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db,
        item_id=item_id,
        requirement_id=requirement_id,
    )
    assert len(_unsettled_run_ids(test_db, requirement_id)) == 1

    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, execution_id),
        state="aborted",
        reason="operator aborted the stalled walk",
    )

    assert _unsettled_run_ids(test_db, requirement_id) == []
    settled = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs "
        "WHERE qa_requirement_id=%s AND performed_by='agent_mission'",
        (requirement_id,),
    ).fetchone()
    assert settled["verdict"] == "error"
    assert "without a review verdict" in settled["verdict_reason"]
    assert find_unsettled_records(test_db, item_id=item_id) == []


def test_repeated_attempts_leave_no_growing_wall_of_orphans(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    # Each abandoned attempt once left one more capture behind, until the
    # terminal transition refused on all of them.
    item_id = 4603
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    for attempt in range(1, 4):
        execution_id = _capture_attempt(
            test_db,
            item_id=item_id,
            requirement_id=requirement_id,
        )
        finish_plan_execution(
            test_db,
            lock_plan_execution(test_db, execution_id),
            state="aborted",
            reason=f"operator aborted attempt {attempt}",
        )

    assert _unsettled_run_ids(test_db, requirement_id) == []
    assert find_unsettled_records(test_db, item_id=item_id) == []


def test_gate_summary_and_terminal_gate_agree_after_review(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4604
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db,
        item_id=item_id,
        requirement_id=requirement_id,
    )
    execution = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, execution)
    _submit_pass(test_db, execution, bundle, requirement_id, "Findings complete.")

    # Gate summary treats any pass row as satisfied; the terminal gate
    # treats a NULL verdict as unsettled. After settlement those two
    # answers agree on this same connection (not an ambient DSN).
    pass_row = test_db.execute(
        "SELECT 1 FROM qa_runs r "
        "JOIN qa_requirements req ON req.id = r.qa_requirement_id "
        "WHERE req.item_id=%s AND r.verdict='pass' LIMIT 1",
        (item_id,),
    ).fetchone()
    assert pass_row is not None
    assert find_unsettled_records(test_db, item_id=item_id) == []

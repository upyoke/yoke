"""A parked walker keeps its QA execution, and continues a swept one."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_agent_mission_qa import _materialize_mission
from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.qa_plan_execution_continuation import contract_baselines
from yoke_core.domain.qa_plan_execution_lifecycle import (
    reap_stale_plan_executions,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
    finish_plan_execution,
    select_plan_execution,
)

MISSION_ACTOR = ActorContext(actor_id="2", session_id="session-agent-mission")
MISSION_TRANSITION = "reviewing-implementation"
LONG_AGO = "2026-01-01T00:00:00Z"


def _stop_reporting(conn: Any, execution_id: str) -> None:
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at=%s WHERE id=%s",
        (LONG_AGO, execution_id),
    )
    conn.commit()


def _set_session_posture(
    conn: Any,
    session_id: str,
    mode: str,
    *,
    reason: str | None = None,
    ended_at: str | None = None,
) -> None:
    conn.execute(
        "UPDATE harness_sessions SET mode=%s, quiet_reason=%s, ended_at=%s "
        "WHERE session_id=%s",
        (mode, reason, ended_at, session_id),
    )
    conn.commit()


def _state(conn: Any, execution_id: str) -> str:
    state = str(select_plan_execution(conn, execution_id, lock=False)["state"])
    conn.rollback()
    return state


def _swept_mission(
    conn: Any,
    tmp_path: Any,
    monkeypatch: Any,
    *,
    item_id: int,
) -> tuple[int, dict[str, Any]]:
    """Settle one mission execution exactly the way the stale sweep does."""
    configure_test_machine(conn, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(conn, item_id=item_id)
    execution = begin_plan_execution(
        conn,
        item_id=item_id,
        transition_id=MISSION_TRANSITION,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    _stop_reporting(conn, str(execution["id"]))
    reaped = reap_stale_plan_executions(conn)
    assert [entry["reaped"] for entry in reaped] == [True]
    settled = select_plan_execution(conn, str(execution["id"]), lock=False)
    conn.rollback()
    return requirement_id, settled


def test_a_parked_owner_keeps_its_execution_and_an_unparked_one_loses_it(
    test_db: Any,
) -> None:
    session_id = "session-parked-walker"
    seed_qa_session(test_db, session_id)
    _materialize_two_cases(test_db, item_id=4901)
    execution = begin_plan_execution(
        test_db,
        item_id=4901,
        transition_id="implemented",
        actor_id="2",
        session_id=session_id,
    )
    execution_id = str(execution["id"])
    _stop_reporting(test_db, execution_id)

    _set_session_posture(test_db, session_id, "parked", reason="holding for the fix")
    assert reap_stale_plan_executions(test_db) == []
    assert _state(test_db, execution_id) == "active"

    _set_session_posture(test_db, session_id, "dash")
    reaped = reap_stale_plan_executions(test_db)
    assert [entry["execution_id"] for entry in reaped] == [execution_id]
    assert _state(test_db, execution_id) == "aborted"


def test_a_parked_session_that_has_ended_shields_nothing(test_db: Any) -> None:
    session_id = "session-parked-then-gone"
    seed_qa_session(test_db, session_id)
    _materialize_two_cases(test_db, item_id=4902)
    execution = begin_plan_execution(
        test_db,
        item_id=4902,
        transition_id="implemented",
        actor_id="2",
        session_id=session_id,
    )
    execution_id = str(execution["id"])
    _stop_reporting(test_db, execution_id)
    _set_session_posture(
        test_db,
        session_id,
        "parked",
        reason="holding for the fix",
        ended_at="2026-01-01T00:05:00Z",
    )

    reaped = reap_stale_plan_executions(test_db)
    assert [entry["execution_id"] for entry in reaped] == [execution_id]
    assert _state(test_db, execution_id) == "aborted"


def test_continuing_a_swept_mission_reaches_no_host_baseline(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    _requirement_id, settled = _swept_mission(
        test_db, tmp_path, monkeypatch, item_id=4903
    )
    assert contract_baselines(settled, settled["roster"][0]) == ("fresh-host",)

    continued = begin_plan_execution(
        test_db,
        item_id=4903,
        transition_id=MISSION_TRANSITION,
        continue_mission=True,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    assert str(continued["continues_execution_id"]) == str(settled["id"])
    assert str(continued["id"]) != str(settled["id"])
    assert continued["state"] == "active"
    assert continued["cursor_ordinal"] == 0
    assert contract_baselines(continued, continued["roster"][0]) == ()
    assert _state(test_db, str(settled["id"])) == "aborted"


def test_continuation_is_refused_when_the_sweep_did_not_settle_the_prior_walk(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _materialize_mission(test_db, item_id=4904)
    execution = begin_plan_execution(
        test_db,
        item_id=4904,
        transition_id=MISSION_TRANSITION,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    finish_plan_execution(
        test_db,
        execution,
        state="aborted",
        reason="case-execution-or-recording-error",
    )

    with pytest.raises(QaPlanExecutionStateError, match="not because the stale sweep"):
        begin_plan_execution(
            test_db,
            item_id=4904,
            transition_id=MISSION_TRANSITION,
            continue_mission=True,
            actor_id=MISSION_ACTOR.actor_id,
            session_id=MISSION_ACTOR.session_id,
        )
    test_db.rollback()


def test_continuation_is_refused_while_the_execution_is_still_live(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _materialize_mission(test_db, item_id=4905)
    begin_plan_execution(
        test_db,
        item_id=4905,
        transition_id=MISSION_TRANSITION,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )

    with pytest.raises(QaPlanExecutionStateError, match="is still live"):
        begin_plan_execution(
            test_db,
            item_id=4905,
            transition_id=MISSION_TRANSITION,
            continue_mission=True,
            actor_id=MISSION_ACTOR.actor_id,
            session_id=MISSION_ACTOR.session_id,
        )
    test_db.rollback()


def test_mission_access_refusal_names_the_continuation_command(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    requirement_id, settled = _swept_mission(
        test_db, tmp_path, monkeypatch, item_id=4906
    )
    outcome = handle_agent_mission_access(
        FunctionCallRequest(
            function="test_machine.mission.access",
            actor=MISSION_ACTOR,
            target=TargetRef(kind="item", item_id=4906),
            payload={
                "execution_id": str(settled["id"]),
                "requirement_id": requirement_id,
            },
        )
    )
    assert outcome.error is not None
    assert outcome.error.code == "agent_mission_access_failed"
    message = outcome.error.message
    assert "the stale sweep settled it" in message
    assert f"--transition {MISSION_TRANSITION}" in message
    assert message.endswith("--continue-mission")


def test_a_continuation_leaves_the_prior_settled_run_as_history(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    requirement_id, settled = _swept_mission(
        test_db, tmp_path, monkeypatch, item_id=4907
    )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "verdict_reason,execution_status,case_outcome,started_at,completed_at,"
        "created_at) VALUES(%s,'agent_mission','plan_case','error',"
        "'settled by execution termination','captured','needs_review',"
        "%s,%s,%s)",
        (requirement_id, LONG_AGO, LONG_AGO, LONG_AGO),
    )
    test_db.commit()

    begin_plan_execution(
        test_db,
        item_id=4907,
        transition_id=MISSION_TRANSITION,
        continue_mission=True,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    prior_runs = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs WHERE qa_requirement_id=%s",
        (requirement_id,),
    ).fetchall()
    assert [(str(row[0]), str(row[1])) for row in prior_runs] == [
        ("error", "settled by execution termination")
    ]
    assert str(settled["release_reason"]) == "stale-heartbeat"

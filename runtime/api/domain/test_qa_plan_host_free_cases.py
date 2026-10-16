"""Host-free automatic cases run and record while a plan waits for its host."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.qa_plan_execution_test_support import (
    TEST_EXECUTION_TARGET,
    TEST_ITEM_ID,
    TEST_ITEM_REF,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import (
    machine_qa_plan_case_execution,
    qa_case_execution,
    qa_plan_execution,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

WAITING = "Queued for QA host test-mac, position 2 of 3. Park now."


def _machine(requirement_id, key, position, *, state="baseline"):
    return {
        "requirement_id": requirement_id,
        "item_id": TEST_ITEM_ID,
        "plan_id": 4,
        "case_key": key,
        "case_position": position,
        "baseline_position": 1,
        "host_baseline": "fresh-host",
        "starting_state": state,
        "runner_id": "host_control",
    }


def _command(requirement_id, key, position, runner="worktree_run"):
    return {
        "requirement_id": requirement_id,
        "item_id": TEST_ITEM_ID,
        "plan_id": 4,
        "case_key": key,
        "case_position": position,
        "baseline_position": 1,
        "host_baseline": None,
        "runner_id": runner,
    }


ROSTER = [
    _machine(301, "anchor", 1),
    _machine(302, "follow", 2, state="inherit"),
    _command(303, "unit", 3),
    _command(304, "ci", 4, runner="ci_run"),
    _command(305, "screens", 5, runner="browser_substrate"),
]


def _run(machine_outcomes, local_outcomes, *, cursor=0, recorded=(), ahead=True):
    """Drive the client loop; machine cases answer in order of dispatch."""
    calls: list[tuple[str, dict]] = []
    dispatched: list[int] = []
    machine_answers = list(machine_outcomes)

    def call_plan_function(**kwargs):
        calls.append((kwargs["function_id"], kwargs["payload"]))
        if kwargs["function_id"] == "qa.plan_execution.begin":
            begun = {
                "execution_id": "plan-execution-host-free",
                "item_id": TEST_ITEM_ID,
                "transition_id": "implemented",
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": cursor,
                "execution_target": TEST_EXECUTION_TARGET,
                "execution_target_digest": "target-digest",
                "requirements": ROSTER,
                "results": [
                    {
                        "ordinal": ordinal,
                        "requirement_id": row["requirement_id"],
                        "result": row,
                    }
                    for ordinal, row in recorded
                ],
            }
            if ahead:
                begun["host_free_cases_ahead"] = True
            return begun
        return {}

    def run_machine(case, **_):
        dispatched.append(int(case["requirement_id"]))
        outcome, verdict = machine_answers.pop(0)
        answer = {
            "requirement_id": case["requirement_id"],
            "case_outcome": outcome,
            "verdict": verdict,
        }
        if verdict == "waiting":
            answer["recovery"] = WAITING
        return answer

    def run_local(case, **_):
        dispatched.append(int(case["requirement_id"]))
        answer = local_outcomes[int(case["requirement_id"])]
        if isinstance(answer, BaseException):
            raise answer
        outcome, verdict = answer
        return {
            "requirement_id": case["requirement_id"],
            "case_outcome": outcome,
            "verdict": verdict,
        }

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=call_plan_function
        ),
        mock.patch.object(
            machine_qa_plan_case_execution,
            "execute_plan_machine_case",
            side_effect=run_machine,
        ),
        mock.patch.object(
            qa_case_execution, "execute_case_context", side_effect=run_local
        ),
    ):
        result = qa_plan_execution.execute_plan(
            public_ref=TEST_ITEM_REF,
            transition_id="implemented",
            actor=ActorContext(actor_id="7", session_id="host-free-plan"),
        )
    advanced = [
        (payload["ordinal"], payload["requirement_id"])
        for name, payload in calls
        if name == "qa.plan_execution.advance"
    ]
    return result, dispatched, advanced, [name for name, _ in calls]


WAIT = ("waiting", "waiting")
PASS = ("passed", "pass")


def test_a_queued_plan_runs_host_free_automatic_cases_before_it_parks() -> None:
    result, dispatched, advanced, calls = _run([WAIT], {303: PASS, 304: PASS})

    assert result["state"] == "waiting"
    # The inherit follower and the agent-judged browser case keep their order.
    assert dispatched == [301, 303, 304]
    assert advanced == [(2, 303), (3, 304)]
    assert "qa.plan_execution.abort" not in calls
    assert [row["requirement_id"] for row in result["results"]] == [303, 304, 301]
    assert result["recovery"].startswith(
        "Ran and recorded host-free case requirements 303, 304 while queued"
    )
    assert result["recovery"].endswith(WAITING)


def test_a_failing_host_free_case_is_recorded_and_the_plan_stays_queued() -> None:
    result, _, advanced, calls = _run(
        [WAIT], {303: ("failed", "fail"), 304: RuntimeError("runner lost")}
    )

    assert result["state"] == "waiting"
    assert advanced == [(2, 303)]
    assert "qa.plan_execution.abort" not in calls
    assert "requirement 304 raised: runner lost" in result["recovery"]
    assert result["recovery"].endswith(WAITING)


def test_resume_skips_recorded_host_free_cases_and_keeps_the_chain_together() -> None:
    recorded = [
        (2, {**_command(303, "unit", 3), "case_outcome": "passed", "verdict": "pass"}),
        (3, {**_command(304, "ci", 4), "case_outcome": "passed", "verdict": "pass"}),
    ]
    result, dispatched, advanced, _ = _run([PASS, PASS], {305: PASS}, recorded=recorded)

    assert dispatched == [301, 302, 305]
    assert advanced == [(4, 305)]
    assert result["executed_count"] == len(ROSTER)


def test_a_server_without_ahead_recording_parks_as_before() -> None:
    result, dispatched, advanced, _ = _run([WAIT], {}, ahead=False)

    assert result["state"] == "waiting"
    assert dispatched == [301]
    assert advanced == []
    assert result["recovery"] == WAITING


def _command_plan_execution(conn):
    insert_item(conn, id=TEST_ITEM_ID, title="Host-free cursor", workflow_id="issue")
    plan = create_plan(conn, project="yoke", slug="host-free", name="Host free")
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": f"Run {key}.",
                "expected_outcome": f"{key} passes.",
                "method_config": {"command": "true"},
            }
            for position, key in enumerate(["first", "second", "third"], start=1)
        ],
    )
    set_project_default(
        conn, plan_id=plan["id"], workflow_id="issue", transition_id="implemented"
    )
    materialize_for_item(conn, item_id=TEST_ITEM_ID, transition_id="implemented")
    return begin_plan_execution(
        conn,
        item_id=TEST_ITEM_ID,
        transition_id="implemented",
        actor_id="7",
        session_id="host-free-cursor",
    )


def _advance(conn, execution, ordinal):
    requirement_id = int(execution["roster"][ordinal]["requirement_id"])
    advance_plan_execution(
        conn,
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        result={"requirement_id": requirement_id, "verdict": "pass"},
    )


def test_the_cursor_steps_over_results_recorded_ahead_exactly_once() -> None:
    with test_database() as conn:
        execution = _command_plan_execution(conn)
        _advance(conn, execution, 2)
        assert execution["cursor_ordinal"] == 0
        _advance(conn, execution, 2)  # an identical replay records nothing new
        _advance(conn, execution, 0)
        assert execution["cursor_ordinal"] == 1
        _advance(conn, execution, 1)
        assert execution["cursor_ordinal"] == 3
        recorded = conn.execute(
            "SELECT ordinal FROM qa_plan_execution_results "
            "WHERE execution_id=%s ORDER BY ordinal",
            (str(execution["id"]),),
        ).fetchall()
        stored = conn.execute(
            "SELECT cursor_ordinal FROM qa_plan_executions WHERE id=%s",
            (str(execution["id"]),),
        ).fetchone()

    assert [int(row[0]) for row in recorded] == [0, 1, 2]
    assert int(stored[0]) == 3


def test_only_host_free_cases_record_ahead_of_the_cursor() -> None:
    with test_database() as conn:
        execution = _command_plan_execution(conn)
        execution["roster"][2]["runner_id"] = "host_control"
        with pytest.raises(QaPlanExecutionStateError, match="expects ordinal 0"):
            _advance(conn, execution, 2)

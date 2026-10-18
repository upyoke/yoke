"""Plan-runner re-entry reprints passing verdicts; other verdicts recapture."""

from __future__ import annotations

from typing import Any
from unittest import mock

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.test_qa_capture_settlement import (
    ACTOR,
    _capture_attempt,
    _materialize_mission,
    _submit_pass,
    _unsettled_run_ids,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_plan_execution
from yoke_core.domain.qa_plan_execution_cli import run
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_terminal_settlement import find_unsettled_records


def test_plan_runner_reprints_settled_review_without_capture():
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs["function_id"])
        if kwargs["function_id"] == "qa.plan.materialize":
            return {}
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "exec-settled",
                "deployment_run_id": "run-settled",
                "deployment_stage": "run-qa",
                "state": "completed",
                "settled_review": [
                    {
                        "requirement_id": 5,
                        "verdict": "pass",
                        "rationale": "the capture shows the fix",
                        "review_run_id": 9,
                    }
                ],
            }
        raise AssertionError(kwargs["function_id"])

    with mock.patch.object(
        qa_plan_execution, "_call_plan_function", side_effect=dispatch
    ):
        result = qa_plan_execution.execute_plan(
            deployment_run_id="run-settled",
            deployment_stage="run-qa",
            deployment_member="YOK-1",
            plan="smoke",
            project="yoke",
            actor=ActorContext(actor_id="2", session_id="owner"),
        )

    assert calls == ["qa.plan.materialize", "qa.plan_execution.begin"]
    assert result["review_status"] == "settled"
    assert result["state"] == "passed"
    assert result["executed_count"] == 0
    assert result["verdicts"][0]["verdict"] == "pass"
    assert "--replaces" in result["recovery"]


def test_cli_reprints_settled_review_and_exits(capsys):
    settled = {
        "state": "passed",
        "review_status": "settled",
        "verdicts": [{"requirement_id": 5, "verdict": "pass"}],
        "recovery": "use --replaces",
    }
    with mock.patch(
        "yoke_core.domain.qa_plan_execution_cli.execute_plan", return_value=settled
    ):
        code = run(
            [
                "--deployment-run-id",
                "run-settled",
                "--stage",
                "run-qa",
                "--member",
                "YOK-1",
                "--project",
                "yoke",
            ]
        )
    captured = capsys.readouterr()
    assert code == 0
    assert '"verdict":"pass"' in captured.out.replace(" ", "")
    assert "already passed" in captured.err
    assert "--replaces" in captured.err


def test_reviewed_attempt_does_not_grow_another_capture(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4603
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db, item_id=item_id, requirement_id=requirement_id
    )
    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, execution_id),
        state="aborted",
        reason="operator aborted attempt 1",
    )
    execution = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, execution, completed_captures_only=True)
    _submit_pass(
        test_db, execution, bundle, requirement_id, "Capture reviewed independently."
    )
    runs = test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
    executions = test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[
        0
    ]
    replay = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    assert replay["id"] == execution_id
    assert replay["settled_review"][0]["verdict"] == "pass"
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == runs
    assert (
        test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0]
        == executions
    )
    assert _unsettled_run_ids(test_db, requirement_id) == []
    assert find_unsettled_records(test_db, item_id=item_id) == []


def _reviewed_aborted_attempt(
    conn: Any, tmp_path: Any, monkeypatch: Any, *, item_id: int, verdict: str
) -> tuple[str, int]:
    requirement_id = _materialize_mission(conn, item_id=item_id)
    configure_test_machine(conn, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        conn, item_id=item_id, requirement_id=requirement_id
    )
    finish_plan_execution(
        conn,
        lock_plan_execution(conn, execution_id),
        state="aborted",
        reason="operator aborted attempt 1",
    )
    execution = lock_plan_execution(conn, execution_id)
    bundle = begin_plan_review(conn, execution, completed_captures_only=True)
    submit_plan_review(
        conn,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": verdict,
                "rationale": f"Capture reviewed independently: {verdict}.",
            }
        ],
        reviewer_actor_id=ACTOR.actor_id,
        reviewer_session_id=ACTOR.session_id,
    )
    return execution_id, requirement_id


def test_failed_review_begins_a_fresh_execution_that_advances(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4604
    execution_id, requirement_id = _reviewed_aborted_attempt(
        test_db, tmp_path, monkeypatch, item_id=item_id, verdict="fail"
    )

    fresh = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )

    assert fresh["id"] != execution_id
    assert "settled_review" not in fresh
    assert [int(row["requirement_id"]) for row in fresh["roster"]] == [requirement_id]
    advance_plan_execution(
        test_db,
        fresh,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": None,
            "case_outcome": "needs_review",
        },
    )
    recorded = test_db.execute(
        "SELECT execution_id FROM qa_plan_execution_results WHERE ordinal=0 "
        "ORDER BY completed_at"
    ).fetchall()
    assert [str(row["execution_id"]) for row in recorded][-1] == str(fresh["id"])

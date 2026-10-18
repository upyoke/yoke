"""Item plan starts select one claimed source from integration and task lanes."""

from unittest.mock import Mock

import pytest

from runtime.api.domain.test_qa_plan_execution_authority import _materialize_two_cases
from runtime.api.fixtures.backlog import insert_epic_task, insert_item_worktree
from runtime.api.fixtures.session_holdings import insert_item_claim
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers, qa_plan_execution
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_begin
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError


@pytest.fixture
def epic_lanes(test_db, tmp_path, monkeypatch):
    item_id = 4401
    _materialize_two_cases(test_db, item_id=item_id)
    test_db.execute("UPDATE items SET workflow_id='epic' WHERE id=%s", (item_id,))
    paths = {}
    for task, branch in enumerate(("integration", "first-worker", "second-worker")):
        path = tmp_path / branch
        path.mkdir()
        lane = insert_item_worktree(
            test_db,
            item_id=item_id,
            branch=branch,
            path=str(path),
            lane_role="worker" if task else "integration",
        )
        test_db.execute(
            "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s",
            ("a" * 40, lane["id"]),
        )
        if task:
            insert_epic_task(
                test_db, epic_id=item_id, task_num=task, item_worktree_id=lane["id"]
            )
        paths[branch] = path
    insert_item_claim(test_db, "plan-owner", item_id)
    test_db.commit()
    connection = Mock(wraps=test_db)
    connection.close = Mock()
    monkeypatch.setattr(db_helpers, "connect", lambda: connection)

    def call(**kwargs):
        assert kwargs["function_id"] == "qa.plan_execution.begin"
        outcome = handle_plan_execution_begin(
            FunctionCallRequest(
                function=kwargs["function_id"],
                actor=kwargs["actor"],
                target=TargetRef(kind="item", item_id=item_id),
                payload=kwargs["payload"],
            )
        )
        if outcome.error:
            raise QaPlanExecutionError(outcome.error.message)
        return outcome.result_payload

    monkeypatch.setattr(qa_plan_execution, "_call_plan_function", call)
    from yoke_core.domain import qa_plan_execution_run

    monkeypatch.setattr(
        qa_plan_execution_run,
        "execute_begun_plan",
        lambda **kwargs: kwargs["execution"],
    )
    return item_id, paths


@pytest.mark.parametrize("branch", ["integration", "first-worker"])
def test_plan_client_and_handler_select_named_epic_lane(epic_lanes, branch):
    item_id, paths = epic_lanes
    result = qa_plan_execution.execute_plan(
        public_ref=f"YOK-{item_id}",
        transition_id="implemented",
        checkout_path=paths[branch],
        expected_branch=branch,
        expected_sha="a" * 40,
        actor=ActorContext(actor_id="1", session_id="plan-owner"),
    )
    assert len(result["requirements"]) == 2
    for case in result["requirements"]:
        assert case["lane_path"] == str(paths[branch])
        assert case["lane_branch"] == branch
        assert case["lane_commit_sha"] == "a" * 40


@pytest.mark.parametrize(
    "selection,session",
    [
        ({}, "plan-owner"),
        ({"checkout": "integration", "branch": "first-worker"}, "plan-owner"),
        ({"checkout": "integration", "branch": "integration"}, "other-session"),
    ],
)
def test_plan_lane_refusal_keeps_actionable_recovery(epic_lanes, selection, session):
    item_id, paths = epic_lanes
    with pytest.raises(
        QaPlanExecutionError, match="qa_source_lane_unresolved"
    ) as error:
        qa_plan_execution.execute_plan(
            public_ref=f"YOK-{item_id}",
            transition_id="implemented",
            checkout_path=paths.get(selection.get("checkout")),
            expected_branch=selection.get("branch"),
            actor=ActorContext(actor_id="1", session_id=session),
        )
    assert (
        "--checkout-path PATH --expected-branch BRANCH --expected-sha FULL_SHA"
        in str(error.value)
    )

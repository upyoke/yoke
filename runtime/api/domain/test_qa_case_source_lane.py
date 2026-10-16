"""A multi-lane QA context takes every identity field from the selected row."""

import json

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_item_worktree,
    insert_epic_task,
)
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.session_holdings import insert_item_claim
from yoke_core.domain.qa_case_execution_context import (
    get_case_execution_context,
    QaCaseExecutionError,
)


@pytest.fixture
def lanes(test_db, tmp_path):
    item_id = 801
    insert_item(test_db, id=item_id, workflow_id="dash")
    paths = {}
    for branch, commit in (("schema-worker", "a" * 40), ("surfaces-worker", None)):
        path = tmp_path / branch
        path.mkdir()
        lane = insert_item_worktree(
            test_db,
            item_id=item_id,
            branch=branch,
            path=str(path),
            lane_role="worker",
        )
        test_db.execute(
            "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s", (commit, lane["id"])
        )
        paths[branch] = path
    insert_item_claim(test_db, "qa-caller", item_id)
    row = insert_qa_requirement(
        test_db,
        item_id=item_id,
        qa_kind="method_case",
        qa_phase="verification",
        method_id="command-ci",
        method_name="CI",
        runner_id="ci_run",
        verdict_path="automatic",
        capability_requirements="[]",
        method_config=json.dumps({"command": "true", "ci_workflow": "ci.yml"}),
    )
    test_db.commit()
    return int(row["id"]), paths


@pytest.mark.parametrize("branch", ["schema-worker", "surfaces-worker"])
def test_selected_lane_keeps_null_commit_without_borrowing_sibling(
    test_db, lanes, branch
):
    requirement, paths = lanes
    context = get_case_execution_context(
        test_db,
        requirement_id=requirement,
        session_id="qa-caller",
        checkout_path=str(paths[branch]),
        expected_branch=branch,
    )
    assert context["lane_branch"] == branch
    assert context["lane_path"] == str(paths[branch])
    assert context["lane_commit_sha"] == (
        "a" * 40 if branch == "schema-worker" else None
    )


def test_multilane_requires_selection_and_matching_claim(test_db, lanes):
    requirement, paths = lanes
    for selection in (
        {},
        {"checkout_path": str(paths["schema-worker"]), "session_id": "other"},
        {
            "checkout_path": str(paths["schema-worker"]),
            "expected_branch": "surfaces-worker",
        },
    ):
        args = {"session_id": "qa-caller", **selection}
        with pytest.raises(QaCaseExecutionError, match="qa_source_lane_unresolved"):
            get_case_execution_context(test_db, requirement_id=requirement, **args)


def test_released_selected_lane_does_not_authorize_a_live_directory(test_db, lanes):
    requirement, paths = lanes
    test_db.execute(
        "UPDATE item_worktrees SET state='released', released_at=CURRENT_TIMESTAMP"
    )
    test_db.commit()
    with pytest.raises(QaCaseExecutionError, match="qa_source_lane_unresolved"):
        get_case_execution_context(
            test_db,
            requirement_id=requirement,
            session_id="qa-caller",
            checkout_path=str(paths["schema-worker"]),
        )


def test_task_claim_selects_only_its_own_lane(test_db, lanes):
    from yoke_core.domain.work_claim_targets import make_epic_task_target

    requirement, paths = lanes
    lane_id = test_db.execute(
        "SELECT id FROM item_worktrees WHERE branch='schema-worker'"
    ).fetchone()[0]
    insert_epic_task(test_db, epic_id=801, task_num=1, item_worktree_id=lane_id)
    test_db.execute(
        "UPDATE work_claims SET target_kind='epic_task', scope=%s WHERE session_id='qa-caller'",
        (make_epic_task_target(801, 1).scope_json(),),
    )
    test_db.commit()
    context = get_case_execution_context(
        test_db, requirement_id=requirement, session_id="qa-caller"
    )
    assert context["lane_path"] == str(paths["schema-worker"])
    assert context["lane_commit_sha"] == "a" * 40
    with pytest.raises(QaCaseExecutionError, match="qa_source_lane_unresolved"):
        get_case_execution_context(
            test_db,
            requirement_id=requirement,
            session_id="qa-caller",
            checkout_path=str(paths["surfaces-worker"]),
        )

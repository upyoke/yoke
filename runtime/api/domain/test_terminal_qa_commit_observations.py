"""Terminal transitions accept item proof without comparing commits."""

import pytest
from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement, insert_qa_run
from runtime.api.domain.test_terminal_qa_settlement import _terminal_result, _tree_result


@pytest.mark.parametrize("sha", ["a" * 40, "b" * 40, ""])
def test_terminal_pass_needs_no_lane_history(test_db, sha):
    insert_item(test_db, id=10, status="release")
    requirement = insert_qa_requirement(test_db, item_id=10)
    insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass",
        raw_result=_tree_result(sha), completed_at="2026-01-01T00:00:01Z")
    assert _terminal_result(test_db) == {"success": True}


def test_replaced_failed_requirement_does_not_block_terminal(test_db):
    from yoke_core.domain.qa_terminal_records import _blocking_requirement_rows

    insert_item(test_db, id=10, status="release")
    successor = insert_qa_requirement(test_db, item_id=10)
    original = insert_qa_requirement(test_db, item_id=10,
        replacement_requirement_id=successor["id"])
    insert_qa_run(test_db, qa_requirement_id=original["id"], verdict="fail")
    insert_qa_run(test_db, qa_requirement_id=successor["id"], verdict="pass")
    assert [row["id"] for row in _blocking_requirement_rows(test_db, 10)] == [successor["id"]]
    assert _terminal_result(test_db) == {"success": True}
    assert test_db.execute("SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s",
        (original["id"],)).fetchone()[0] == "fail"


def test_terminal_does_not_expand_item_scope(test_db):
    from yoke_core.domain.qa_terminal_records import _blocking_requirement_rows

    insert_item(test_db, id=10, status="release")
    insert_item(test_db, id=11)
    own = insert_qa_requirement(test_db, item_id=10)
    from runtime.api.fixtures.backlog_inserts import insert_deployment_run

    insert_qa_requirement(test_db, item_id=None, epic_id=10, task_num=1)
    run = insert_deployment_run(test_db)
    insert_qa_requirement(test_db, item_id=None, deployment_run_id=run["id"],
        deployment_stage="release", deployment_member_item_id=10)
    assert [row["id"] for row in _blocking_requirement_rows(test_db, 10)] == [own["id"]]

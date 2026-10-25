"""Merge uses the common reader's native-selected run, never history order."""

import json
from itertools import permutations

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.domain.test_standalone_item_merge_qa import MERGING_SHA, _item
from yoke_core.domain.item_detail_qa import qa_rows
from yoke_core.domain.standalone_item_merge_qa import preflight


def _capture(conn, requirement_id, ordinal, verdict, *, proof=True):
    stamp = f"2026-10-01T00:00:0{ordinal}Z"
    return insert_qa_run(
        conn,
        qa_requirement_id=requirement_id,
        verdict=verdict,
        started_at=stamp,
        created_at=stamp,
        completed_at=stamp if verdict else None,
        case_outcome="passed"
        if verdict == "pass"
        else ("failed" if verdict else "running"),
        raw_result=json.dumps({"verification_tree": {"head_sha": MERGING_SHA}})
        if proof
        else "{}",
    )


def _proof(conn, item_id, tmp_path):
    item = _item(None)
    item["qa_requirements"] = qa_rows(conn, item_id)
    return item, preflight(
        item, public_ref="example", repo_root=tmp_path, branch="lane"
    )


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_newest_passing_attempt_grades_the_same_in_every_history_order(
    test_db, tmp_path, order
):
    item = insert_item(test_db)
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    captures = {}
    for ordinal in order:
        captures[ordinal] = _capture(
            test_db, requirement["id"], ordinal, [None, "fail", "pass"][ordinal]
        )
    model, result = _proof(test_db, item["id"], tmp_path)
    assert result == (MERGING_SHA, "")
    assert model["qa_requirements"][0]["run_id"] == captures[2]["id"]
    assert model["qa_requirements"][0]["case_outcome"] == "passed"


@pytest.mark.parametrize("verdict", ["fail", None])
def test_current_failed_or_pending_attempt_cannot_borrow_an_old_pass(
    test_db, tmp_path, verdict
):
    item = insert_item(test_db)
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    current = _capture(test_db, requirement["id"], 2, verdict)
    _capture(test_db, requirement["id"], 1, "pass")
    model, (_, error) = _proof(test_db, item["id"], tmp_path)
    assert "incomplete" in error
    assert model["qa_requirements"][0]["run_id"] == current["id"]


def test_selected_run_without_start_commit_cannot_borrow_old_proof(test_db, tmp_path):
    item = insert_item(test_db)
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    current = _capture(test_db, requirement["id"], 2, "pass", proof=False)
    _capture(test_db, requirement["id"], 1, "pass")
    model, (_, error) = _proof(test_db, item["id"], tmp_path)
    assert "outside-lane" in error
    assert model["qa_requirements"][0]["run_id"] == current["id"]
    assert not model["qa_requirements"][0]["recorded_head_sha"]

"""Retained item plan copies are history, never obligations or evidence."""

import pytest

from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement, insert_qa_run
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from yoke_core.domain.qa_terminal_settlement import find_unsettled_records, _blocking_requirement_rows
from yoke_core.domain.post_deploy_verification_answer import answer_for_item, UNANSWERED
from yoke_core.domain.qa_browser_evidence_check import check_browser_artifact_disk


@pytest.mark.parametrize("disposition", ["unsettled", "waived", "superseded"])
def test_retained_copy_cannot_answer_or_block_item(test_db, disposition):
    item = insert_item(test_db, status="release")
    plan = _plan(test_db, "history-only")
    row = insert_qa_requirement(
        test_db, item_id=item["id"], plan_id=plan, qa_phase="post_deploy",
        method_id="browser-inspection", workflow_transition_id="done",
    )
    insert_qa_run(test_db, qa_requirement_id=row["id"], verdict=None)
    if disposition == "waived":
        test_db.execute("UPDATE qa_requirements SET waived_at=now() WHERE id=%s", (row["id"],))
    if disposition == "superseded":
        test_db.execute("UPDATE qa_requirements SET superseded_by_requirement_id=id WHERE id=%s", (row["id"],))
    test_db.commit()
    assert answer_for_item(test_db, item["id"]).verdict == UNANSWERED
    assert find_unsettled_records(test_db, item_id=item["id"]) == []
    assert _blocking_requirement_rows(test_db, item["id"]) == []
    assert check_browser_artifact_disk(
        test_db, where="r.item_id=%s", params=(item["id"],), name="sample",
        transition_name="done", repo_root=None,
    ) is None

"""Detailed proof is opt-in and reads each requirement cohort once."""

import json
import pytest
from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement, insert_qa_run
from yoke_core.domain import qa_terminal_records as records
from yoke_core.domain.item_detail_qa import qa_rows
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues


def test_ordinary_item_detail_does_not_grade_terminal_proof(test_db, monkeypatch):
    item = insert_item(test_db)
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    run = insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass")

    def forbidden(*_):
        pytest.fail("ordinary item detail must not invoke the full proof reader")

    monkeypatch.setattr(records, "_blocking_requirement_rows", forbidden)
    [row] = qa_rows(test_db, item["id"])
    assert row["run_id"] == run["id"]
    assert "current_passing_proof" not in row


def test_merge_proof_reads_one_cohort(test_db, monkeypatch):
    item = insert_item(test_db)
    for _ in range(3):
        requirement = insert_qa_requirement(test_db, item_id=item["id"])
        insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass")
    reader = records._blocking_requirement_rows
    calls = []

    def counted(conn, item_id):
        calls.append(item_id)
        return reader(conn, item_id)

    monkeypatch.setattr(records, "_blocking_requirement_rows", counted)
    rows = qa_rows(test_db, item["id"], include_proof=True)
    assert len(rows) == 3
    assert all(row["current_passing_proof"] for row in rows)
    assert calls == [item["id"]]


@pytest.mark.parametrize("phase", ["verification", "post_deploy"])
@pytest.mark.parametrize("digest", ["frozen", "wrong"])
def test_deployment_pass_retains_frozen_release_target_binding(test_db, phase, digest):
    from runtime.api.fixtures.backlog_inserts import insert_deployment_run
    from yoke_core.domain.qa_latest_execution import latest_executions
    from yoke_core.domain.qa_requirement_pass_currency import current_passing_requirements

    run = insert_deployment_run(test_db)
    requirement = insert_qa_requirement(test_db, item_id=None,
        deployment_run_id=run["id"], deployment_stage="release",
        qa_phase=phase, execution_target_digest="frozen")
    insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass",
        raw_result=json.dumps({"execution_target_digest": digest}))
    attempt = latest_executions(test_db, [requirement["id"]])[requirement["id"]]
    proof = dict(requirement, run_id=attempt["id"], verdict=attempt["verdict"],
        completed_at=attempt["completed_at"], subject_proof_error="",
        current_passing_proof=requirement["id"] in current_passing_requirements(test_db, [requirement["id"]]))
    issues = blocking_requirement_issues([proof], public_ref="example", require_any=True)
    assert [issue.state for issue in issues] == ([] if digest == "frozen" else ["stale-proof"])

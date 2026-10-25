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
    item = insert_item(test_db)
    requirement = insert_qa_requirement(test_db, item_id=item["id"],
        qa_phase=phase, execution_target_digest="frozen")
    # A deployment-bound row takes its release identity from the frozen target,
    # independently of the optional start commit observation.
    row = dict(requirement, deployment_run_id="release")
    insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass",
        raw_result=json.dumps({"execution_target_digest": digest}))
    [proof] = records._blocking_requirement_rows(test_db, item["id"])
    proof.pop("post_deploy_consumed", None)
    proof.update(deployment_run_id=row["deployment_run_id"])
    issues = blocking_requirement_issues([proof], public_ref="example", require_any=True)
    assert [issue.state for issue in issues] == ([] if digest == "frozen" else ["stale-proof"])

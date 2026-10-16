"""Deployment copy identity, shared membership and release history in the UI read."""

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_run
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.fixtures.completed_delivery import seed_selected_requirement_run
from runtime.api.fixtures.deployment_admitted_case_fixture import admitted_copy
from yoke_core.domain.deployment_member_qa_projection import member_qa_obligations
from yoke_core.domain.db_helpers import query_rows


def read(conn, run_id, members):
    runs = query_rows(
        conn,
        "SELECT dr.*,df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
        (run_id,),
    )
    items = [
        {"id": member, "ref": f"SAMPLE-{member}", "project_id": 1, "project": "yoke"}
        for member in members
    ]
    return member_qa_obligations(conn, runs, {run_id: items})


def test_pending_queued_verdict_and_takeover_are_scoped_to_their_release(test_db):
    item = 9710
    insert_item(
        test_db, id=item, project_sequence=710, workflow_id="issue", status="done"
    )
    source = _original_requirement(
        test_db, item_id=item, method_id="browser-inspection"
    )
    first = "run-visible-qa-first"
    seed_selected_requirement_run(
        test_db, run_id=first, item_id=item, requirement_id=source
    )
    pending = read(test_db, first, [item])[(first, item)]
    assert "error" not in pending, pending
    assert pending["current"][0]["source_requirement_id"] == source
    assert pending["current"][0]["pending_obligation"]
    copy = admitted_copy(test_db, run_id=first, item_id=item)
    queued = read(test_db, first, [item])[(first, item)]
    assert "error" not in queued, queued
    assert [row["requirement_id"] for row in queued["current"]] == [copy]
    assert queued["current"][0]["run_id"] is None
    attempt = insert_qa_run(test_db, qa_requirement_id=copy, verdict="fail")
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,created_at) "
        "VALUES(%s,'command_output',%s)",
        (attempt["id"], attempt["created_at"]),
    )
    test_db.commit()
    failed = read(test_db, first, [item])[(first, item)]["current"][0]
    assert failed["run_id"] == attempt["id"]
    assert failed["outcome"] == "failed"
    assert failed["evidence_count"] == 1
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (first,))
    test_db.commit()
    replacement = "run-visible-qa-next"
    seed_selected_requirement_run(
        test_db, run_id=replacement, item_id=item, requirement_id=source
    )
    next_pending = read(test_db, replacement, [item])[(replacement, item)]
    assert len(next_pending["current"]) == 1
    assert next_pending["current"][0]["pending_obligation"]
    assert next_pending["current"][0]["artifacts"] == []
    assert next_pending["history"] == []
    assert (
        read(test_db, first, [item])[(first, item)]["current"][0]["outcome"] == "failed"
    )


def test_completed_release_preserves_definition_after_source_retraction(test_db):
    item = 9711
    insert_item(
        test_db, id=item, project_sequence=711, workflow_id="issue", status="done"
    )
    source = _original_requirement(
        test_db, item_id=item, method_id="browser-inspection"
    )
    run_id = "run-visible-qa-history"
    seed_selected_requirement_run(
        test_db, run_id=run_id, item_id=item, requirement_id=source
    )
    copy = admitted_copy(test_db, run_id=run_id, item_id=item)
    insert_qa_run(test_db, qa_requirement_id=copy, verdict="pass")
    before = read(test_db, run_id, [item])[(run_id, item)]["current"][0]
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    test_db.execute(
        "UPDATE qa_requirements SET instructions='later edit',retracted_at=created_at WHERE id=%s",
        (source,),
    )
    test_db.commit()
    after = read(test_db, run_id, [item])[(run_id, item)]["current"][0]
    assert after["requirement_id"] == copy
    assert after["instructions"] == before["instructions"]
    assert after["outcome"] == "passed"


def test_shared_plan_copy_is_associated_only_with_its_carriers(test_db):
    from runtime.api.domain.test_deployment_qa_shared_admitted_plans import (
        _seed,
        _materialize,
        MEMBERS,
        RUN,
    )

    _seed(test_db, MEMBERS[:2])
    copy = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    _materialize(test_db, MEMBERS[1])
    insert_qa_run(test_db, qa_requirement_id=copy, verdict="pass")
    results = read(test_db, RUN, MEMBERS)
    for member in MEMBERS[:2]:
        assert "error" not in results[(RUN, member)], results[(RUN, member)]
        assert [row["requirement_id"] for row in results[(RUN, member)]["current"]] == [
            copy
        ]
    assert results[(RUN, MEMBERS[2])]["current"] == []


def test_active_source_edit_does_not_borrow_the_old_copy_pass(test_db):
    item = 9712
    insert_item(
        test_db, id=item, project_sequence=712, workflow_id="issue", status="done"
    )
    source = _original_requirement(
        test_db, item_id=item, method_id="browser-inspection"
    )
    run_id = "run-visible-qa-correction"
    seed_selected_requirement_run(
        test_db, run_id=run_id, item_id=item, requirement_id=source
    )
    copy = admitted_copy(test_db, run_id=run_id, item_id=item)
    insert_qa_run(test_db, qa_requirement_id=copy, verdict="pass")
    test_db.execute(
        "UPDATE qa_requirements SET instructions='Corrected probe' WHERE id=%s",
        (source,),
    )
    test_db.commit()
    result = read(test_db, run_id, [item])[(run_id, item)]
    assert result["current"][0]["pending_obligation"]
    assert result["current"][0]["instructions"] == "Corrected probe"
    assert result["current"][0]["artifacts"] == []
    assert [row["requirement_id"] for row in result["history"]] == [copy]

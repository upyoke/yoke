"""Release QA settles from real verdict writes and preserves group evidence."""

from uuid import uuid4

from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import seed_member_qa_case
from runtime.api.fixtures.session_holdings import insert_item_claim
from yoke_core.domain.yoke_function_dispatch import dispatch


def test_individual_case_complete_finishes_release_without_plan_walk(test_db):
    run_id, member, session = "run-individual-case-completes", 9981, "direct-case-owner"
    requirement = seed_member_qa_case(test_db, run_id=run_id, member_item_id=member)
    release_seeded_driver(test_db, run_id)
    actor = register_session_actor(test_db, session)
    insert_item_claim(test_db, session, member)
    test_db.commit()

    def call(function, payload):
        response = dispatch({
            "function": function, "request_id": str(uuid4()),
            "actor": {"actor_id": str(actor), "session_id": session},
            "target": {"kind": "qa_requirement", "qa_requirement_id": requirement},
            "payload": payload,
        })
        assert response.success, response.error
        return response.result

    started = call("qa.run.add", {"performed_by": "worktree_run"})
    qa_run = started["qa_run_id"]
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES (%s,'log','evidence://direct-case',now())", (qa_run,))
    test_db.commit()
    call("qa.run.complete", {"run_id": qa_run, "verdict": "pass"})
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0
    assert test_db.execute("SELECT status FROM deployment_runs WHERE id=%s", (run_id,)).fetchone()[0] == "succeeded"

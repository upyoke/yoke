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


def test_retry_refuses_old_model_release(test_db):
    import pytest
    from runtime.api.domain.test_delete_post_deploy_item_qa_copies_migration import (
        _plan, _member, _copy,
    )
    from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
    from yoke_core.domain.qa_deployment_run_settlement import restore_retry_obligations

    item, run_id = 9982, "run-old-model-retry"
    insert_item(test_db, id=item, status="release")
    plan = _plan(test_db)
    insert_deployment_run(test_db, id=run_id, status="failed")
    _member(test_db, run_id, item,
            {"schema": 1, "requirements": [], "plans": [{"plan": {"id": plan}}]})
    _copy(test_db, None, plan, deployment_run_id=run_id,
          deployment_member_item_id=item, deployment_stage="item-qa")
    test_db.commit()
    with pytest.raises(ValueError, match="old_model_plan_run_retry_refused.*new release run"):
        restore_retry_obligations(test_db, run_id)


def test_failed_group_takeover_reuses_passes(test_db):
    from runtime.api.domain.test_deployment_qa_plan_groups import RUN, SLUG, _seed, _begin
    from runtime.api.domain.test_deployment_qa_plan_group_takeover import _take_over, NEW
    from runtime.api.domain.test_qa_plan_run_target_partition import _pass
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.domain.qa_plan_execution_state import finish_plan_execution, begin_plan_execution
    from yoke_core.domain.qa_deployment_run_settlement import settle_unsuccessful_run

    plan = _seed(test_db)
    replace_plan_cases(test_db, plan_id=plan, cases=[{
        "case_key": key, "position": n, "method_id": "command",
        "instructions": "Run the smoke command.", "expected_outcome": "It passes.",
        "method_config": {"command": "true"},
    } for n, key in enumerate(("first", "second"), 1)])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    execution = _begin(test_db)
    passed = _pass(test_db, execution, 0)
    unpassed = execution["roster"][1]["requirement_id"]
    finish_plan_execution(test_db, execution, state="error", reason="second case failed")
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (RUN,))
    settle_unsuccessful_run(test_db, RUN, reason="release failed")
    test_db.commit()
    _take_over(test_db, plan)
    fresh = begin_plan_execution(test_db, deployment_run_id=NEW, deployment_stage="item-qa",
        plan=SLUG, actor_id="2", session_id="successor-qa")
    assert [row["requirement_id"] for row in fresh["roster"]] == [unpassed]
    assert passed != unpassed

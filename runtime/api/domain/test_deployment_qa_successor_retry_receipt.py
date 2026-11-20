"""A fresh successor retry preserves the inherited pass and failed attempt.

The inherited fail answered the predecessor's target, so once the case
rebinds it reads as unrun: the stage waits for the retry instead of blocking
and nobody is handed a failure to act on.
"""

from runtime.api.domain.deployment_qa_successor_retry_test_support import (
    _pinned_release as _pinned_release,
)

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.deployment_qa_successor_retry_test_support import (
    MEMBER,
    HOLDER_A,
    _seed_member_execution,
    _record,
    _release,
    _take_over_and_deploy,
    _bodies,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_failure_handoff import (
    failure_handoff_key,
    notify_member_qa_failure,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import plan_execution_view
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.deployment_run_project_sources import run_source_sha


def test_a_failed_case_is_retried_on_the_successor_without_a_failure_handoff(
    test_db, monkeypatch
):
    execution = _seed_member_execution(test_db, monkeypatch)
    passed, pass_run = _record(test_db, execution, 0, "pass")
    failed, fail_run = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    assert _release(plan_execution_view(test_db, execution)) == "v-aaaaaa"
    _take_over_and_deploy(test_db)
    from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage

    materialize_deployment_qa_stage(test_db, deployment_run_id=takeover.NEW,
        deployment_stage="item-qa", deployment_member_item_id=MEMBER)

    status = deployment_qa_stage_status(
        test_db, run_id=takeover.NEW, stage_name="item-qa", member_item_id=MEMBER
    )
    assert status["outcome"] == "waiting"
    assert {
        (int(f["requirement_id"]), f["kind"]) for f in status["case_failures"]
    } == {(failed, "unrun")}
    key = failure_handoff_key(
        takeover.NEW, "item-qa", MEMBER, str(status["target_digest"]), fail_run
    )
    delivery = notify_member_qa_failure(
        test_db, run_id=takeover.NEW, stage="item-qa", item_id=MEMBER, status=status
    )
    assert delivery == ""
    assert _bodies(test_db, key) == []

    from yoke_core.domain.qa_plan_rematerialize_deployment import (
        rematerialize_for_deployment_stage,
    )
    refreshed = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    assert refreshed["created_requirement_ids"] == []
    retry = begin_plan_execution(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="1",
        session_id=HOLDER_A,
    )
    assert retry["id"] != execution["id"]
    assert [int(case["requirement_id"]) for case in retry["roster"]] == [failed]
    assert retry["execution_target_digest"] != execution["execution_target_digest"]
    assert _release(plan_execution_view(test_db, retry)) == "v-cccccc"
    context = get_case_execution_context(test_db, requirement_id=failed)
    assert context["deployment_source_revision"] == run_source_sha(
        test_db, takeover.NEW, int(context["project_id"])
    )
    verdicts = dict(
        test_db.execute(
            "SELECT id,verdict FROM qa_runs WHERE id=ANY(%s)", ([pass_run, fail_run],)
        ).fetchall()
    )
    assert verdicts == {pass_run: "pass", fail_run: "fail"}
    assert passed != failed

"""A fresh successor retry preserves the inherited pass and failed attempt."""

import pytest

from runtime.api.domain.test_deployment_qa_successor_retry import (
    _pinned_release as _pinned_release,
)

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_successor_retry import (
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


def test_a_failed_case_is_retried_on_the_successor_and_its_owner_told_once(
    test_db, monkeypatch
):
    execution = _seed_member_execution(test_db, monkeypatch)
    passed, pass_run = _record(test_db, execution, 0, "pass")
    failed, fail_run = _record(test_db, execution, 1, "fail")
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")
    assert _release(plan_execution_view(test_db, execution)) == "v-aaaaaa"
    _take_over_and_deploy(test_db)

    status = deployment_qa_stage_status(
        test_db, run_id=takeover.NEW, stage_name="item-qa", member_item_id=MEMBER
    )
    assert status["outcome"] == "blocked"
    key = failure_handoff_key(
        takeover.NEW, "item-qa", MEMBER, str(status["target_digest"]), fail_run
    )
    for _ in range(2):  # A repeat dispatch sends no duplicate.
        delivery = notify_member_qa_failure(
            test_db, run_id=takeover.NEW, stage="item-qa", item_id=MEMBER, status=status
        )
        assert delivery in {"delivered", "undelivered"}, (
            delivery,
            status["case_failures"],
        )
    # HOLDER_A produced the FAIL itself and still gets exactly one retry notice.
    [body] = _bodies(test_db, key)
    assert "contains the item's merge; retry the case" in body
    from yoke_core.domain.project_identity import render_item_ref

    ref = render_item_ref(test_db, MEMBER)
    assert f"yoke qa plan run --item {ref} --stage item-qa --project yoke" in body

    from yoke_core.domain.qa_plan_rematerialize_deployment import (
        rematerialize_for_deployment_stage,
    )
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    with pytest.raises(
        QaPlanExecutionStateError, match="qa_successor_target_not_materialized"
    ):
        begin_plan_execution(
            test_db,
            deployment_run_id=takeover.NEW,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER,
            actor_id="1",
            session_id=HOLDER_A,
        )
    refreshed = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    [corrected] = refreshed["created_requirement_ids"]
    retry = begin_plan_execution(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="1",
        session_id=HOLDER_A,
    )
    assert retry["id"] != execution["id"]
    assert [int(case["requirement_id"]) for case in retry["roster"]] == [corrected]
    assert corrected != failed
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

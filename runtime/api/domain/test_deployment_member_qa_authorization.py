"""A bound project's member owns its QA writes in a shared release."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.bound_source_release import (
    CONSUMER_ITEM_ID,
    CONSUMER_PROJECT,
    UNBOUND_ITEM_ID,
)
from runtime.api.fixtures.carried_release_candidate import item_ref
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.qa_deployment_function_subject import QaSubjectProjectError
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.browser_qa_case_target import resolve_case_deployment_under_test
from yoke_core.domain.handlers.qa_case_execution import handle_case_execution_begin
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_start_bound_authority import PAYLOAD_KEY
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


from runtime.api.domain.deployment_member_qa_authorization_test_support import (
    RUN,
    STAGE,
    _consumer_actor,
    _entry,
    _mixed_run,
    _request,
)


def test_member_project_authorizes_every_plan_leg_and_requirement(
    test_db, tmp_path, monkeypatch
):
    conn = test_db
    release = _mixed_run(conn, tmp_path, monkeypatch)
    actor_id = _consumer_actor(conn, release["consumer_id"])
    member = release["consumer_ref"]
    request = _request("qa.plan.materialize", member=member)
    request.actor.actor_id = str(actor_id)
    assert resolve_project_context(conn, _entry(request.function), request) == (
        release["consumer_id"],
        CONSUMER_PROJECT,
    )
    assert (
        check_dispatch_permission(conn, _entry(request.function), request).error is None
    )
    with mock.patch(
        "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
        return_value={"id": 17, "session_id": "consumer-qa"},
    ):
        assert qa_subject_claim_verdict(request)[0]
    materialized = materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=CONSUMER_ITEM_ID,
        agent_plan="consumer-smoke",
    )
    requirement_id = materialized["created_requirement_ids"][0]
    assert materialized["candidate_revision"] == str(
        conn.execute(
            "SELECT release_lineage FROM deployment_runs WHERE id=%s", (RUN,)
        ).fetchone()[0]
    )
    browser_target = resolve_case_deployment_under_test(
        conn, requirement_id=requirement_id, project_id=release["consumer_id"]
    )
    assert browser_target is not None and not browser_target.unresolved
    browser_request = FunctionCallRequest(
        function="qa.browser_context.get",
        actor=ActorContext(actor_id=str(actor_id), session_id="consumer-qa"),
        target=TargetRef(
            kind="deployment_run", deployment_run_id=RUN, project_id=CONSUMER_PROJECT
        ),
        payload={"project": CONSUMER_PROJECT, "requirement_id": requirement_id},
    )
    assert (
        check_dispatch_permission(
            conn, _entry(browser_request.function), browser_request
        ).error
        is None
    )
    with mock.patch(
        "yoke_core.domain.qa_start_bound_authority.resolve_start_bound_claim_id",
        return_value=17,
    ) as bound_claim:
        case_contract = handle_case_execution_begin(
            _request("qa.case_execution.begin", requirement_id=requirement_id)
        )
    assert case_contract.primary_success
    assert case_contract.result_payload["case"][PAYLOAD_KEY] == 17
    assert bound_claim.call_args.kwargs["item_id"] == CONSUMER_ITEM_ID
    execution = begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=CONSUMER_ITEM_ID,
        actor_id=str(actor_id),
        session_id="consumer-qa",
    )
    for function in ("qa.plan_execution.begin", "qa.plan.rematerialize"):
        leg = _request(function, member=member)
        leg.actor.actor_id = str(actor_id)
        assert resolve_project_context(conn, _entry(function), leg) == (
            release["consumer_id"],
            CONSUMER_PROJECT,
        )
        assert check_dispatch_permission(conn, _entry(function), leg).error is None
    for function in (
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.complete",
        "qa.plan_execution.abort",
        "qa.plan_review.begin",
        "qa.plan_review.submit",
    ):
        leg = _request(function, execution_id=str(execution["id"]))
        leg.actor.actor_id = str(actor_id)
        assert resolve_project_context(conn, _entry(function), leg) == (
            release["consumer_id"],
            CONSUMER_PROJECT,
        )
        assert check_dispatch_permission(conn, _entry(function), leg).error is None
        with mock.patch(
            "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
            return_value={"id": 17, "session_id": "consumer-qa"},
        ):
            assert qa_subject_claim_verdict(leg)[0]
    direct_case = _request("qa.requirement.add", member=member)
    direct_case.actor.actor_id = str(actor_id)
    direct_case.payload = {"deployment_stage": STAGE, "deployment_member_item": member}
    assert (
        check_dispatch_permission(conn, _entry(direct_case.function), direct_case).error
        is None
    )
    for function in (
        "qa.case_execution.begin",
        "qa.run.add",
        "qa.run.complete",
        "qa.run.record_verdict",
        "qa.requirement.update",
        "qa.artifact.add",
    ):
        leg = _request(function, requirement_id=requirement_id)
        leg.actor.actor_id = str(actor_id)
        assert resolve_project_context(conn, _entry(function), leg) == (
            release["consumer_id"],
            CONSUMER_PROJECT,
        )
        assert check_dispatch_permission(conn, _entry(function), leg).error is None
        with mock.patch(
            "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
            return_value={"id": 17, "session_id": "consumer-qa"},
        ):
            verdict = qa_subject_claim_verdict(leg)
            assert verdict[0], verdict
    qa_run_id = record_case_verdict(conn, requirement_id, "pass", evidence=True)
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": qa_run_id,
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    assert (
        conn.execute(
            "SELECT state FROM qa_plan_executions WHERE id=%s", (execution["id"],)
        ).fetchone()[0]
        == "completed"
    )


def test_member_scope_refuses_wrong_project_sibling_and_run_qa(
    test_db, tmp_path, monkeypatch
):
    conn = test_db
    release = _mixed_run(conn, tmp_path, monkeypatch)
    actor_id = _consumer_actor(conn, release["consumer_id"])
    member = release["consumer_ref"]
    bad_hint = _request("qa.plan.materialize", member=member, project="yoke")
    with pytest.raises(QaSubjectProjectError, match="does not match"):
        resolve_project_context(conn, _entry(bad_hint.function), bad_hint)
    outsider = _request("qa.plan.materialize", member="CNS-999999")
    with pytest.raises(QaSubjectProjectError, match="not found"):
        resolve_project_context(conn, _entry(outsider.function), outsider)
    insert_item(
        conn,
        id=UNBOUND_ITEM_ID,
        project_sequence=UNBOUND_ITEM_ID,
        project=CONSUMER_PROJECT,
        workflow_id="blitz",
        status="implementing",
    )
    conn.commit()
    nonmember = _request("qa.plan.materialize", member=item_ref(conn, UNBOUND_ITEM_ID))
    with pytest.raises(QaSubjectProjectError, match="not an attached member"):
        resolve_project_context(conn, _entry(nonmember.function), nonmember)
    create_smoke_plan(conn, project="yoke", slug="carrier-smoke")
    from yoke_core.domain.qa_plan_management import QaPlanError

    with pytest.raises(QaPlanError, match="not active in this project"):
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=CONSUMER_ITEM_ID,
            agent_plan="carrier-smoke",
        )
    sibling = _request(
        "qa.plan.materialize", member=release["carrier_ref"], project="yoke"
    )
    sibling.actor.actor_id = str(actor_id)
    assert (
        check_dispatch_permission(conn, _entry(sibling.function), sibling).error
        is not None
    )
    run_request = _request("qa.plan.materialize", project="yoke")
    run_request.actor.actor_id = str(actor_id)
    assert (
        check_dispatch_permission(conn, _entry(run_request.function), run_request).error
        is not None
    )
    wrong_stage = _request("qa.plan.materialize", member=member)
    wrong_stage.payload["deployment_stage"] = "hosted-release"
    with pytest.raises(QaSubjectProjectError, match="not a pinned QA stage"):
        resolve_project_context(conn, _entry(wrong_stage.function), wrong_stage)
    with mock.patch(
        "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
        return_value={"id": 17, "session_id": "another-session"},
    ):
        assert not qa_subject_claim_verdict(
            _request("qa.plan.materialize", member=member)
        )[0]

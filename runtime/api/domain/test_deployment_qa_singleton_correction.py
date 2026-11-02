"""Correcting member-owned attached plans preserves their scope and evidence."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    _attach,
    _seed,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _fail
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case, _plan
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_plan_ownership import _snapshot
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_stage_entry import set_current_stage
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_item_deployment_request import resolve_item_deployment_request
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_replacement import declare_replacements

STAGE = "item-qa"


def _subject(member=MEMBERS[0]):
    return dict(
        deployment_run_id=RUN, deployment_stage=STAGE, deployment_member_item_id=member
    )


def _single(conn):
    plan = _seed(conn, attached=MEMBERS[:1])
    set_current_stage(conn, RUN, STAGE)
    conn.commit()
    materialized = materialize_deployment_qa_stage(conn, **_subject())
    return plan, materialized["created_requirement_ids"][0]


def _correct(conn, plan):
    replace_plan_cases(
        conn,
        plan_id=plan,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the corrected member probe.",
                "expected_outcome": "The corrected probe passes.",
                "method_config": {"command": "echo corrected"},
            }
        ],
    )


def _request(conn, plan):
    return FunctionCallRequest(
        function="qa.plan.rematerialize",
        actor=ActorContext(actor_id="2", session_id="owner"),
        target=TargetRef(kind="item", item_id=MEMBERS[0], project_id="1"),
        payload={"deployment_stage": STAGE, "plan": str(plan)},
    )


@pytest.mark.parametrize("kind", ["single", "shared", "correction"])
def test_explicit_item_plan_keeps_member_unless_the_plan_is_shared(
    test_db, monkeypatch, kind
):
    from yoke_core.domain import qa_item_deployment_request as routing

    plan = _seed(test_db, attached=MEMBERS if kind == "shared" else MEMBERS[:1])
    set_current_stage(test_db, RUN, STAGE)
    test_db.commit()
    if kind == "correction":
        plan = _plan(test_db, "member-correction")
    monkeypatch.setattr(
        routing, "latest_qa_member_run", lambda *args, **kwargs: {"id": RUN}
    )
    request = resolve_item_deployment_request(test_db, _request(test_db, plan))
    assert request.target.deployment_run_id == RUN
    if kind == "shared":
        assert "deployment_member" not in request.payload
    else:
        assert request.payload["deployment_member"] == render_item_ref(
            test_db, MEMBERS[0]
        )


def test_failed_singleton_rematerializes_its_pinned_contract_and_credits_member(
    test_db,
):
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    plan, failed = _single(test_db)
    before = _snapshot(test_db, RUN)
    _fail(test_db, failed)
    _correct(test_db, plan)
    result = rematerialize_for_deployment_stage(test_db, **_subject(), plan=str(plan))
    corrected = result["created_requirement_ids"]
    assert len(corrected) == 1 and corrected != [failed]
    after = _snapshot(test_db, RUN)
    assert after["item_qa_plan_owners"] == before["item_qa_plan_owners"]
    assert (
        after["plan_groups"][str(plan)]["cases"][0]["instructions"]
        == "Run the corrected member probe."
    )
    old = test_db.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (failed,)
    ).fetchone()
    assert old[0] == before["plan_groups"][str(plan)]["cases"][0]["instructions"]
    execution = begin_plan_execution(
        test_db, **_subject(), plan=str(plan), actor_id="2", session_id="owner"
    )
    assert [row["requirement_id"] for row in execution["roster"]] == corrected
    _complete_case(test_db, execution)
    assert current_item_qa(
        test_db, run_id=RUN, item_id=MEMBERS[0], current_stage=STAGE
    ).accepted


def test_new_correction_plan_replaces_only_the_selected_member_failure(test_db):
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    plan, failed = _single(test_db)
    _fail(test_db, failed)
    correction = _plan(test_db, "correction-only")
    _correct(test_db, correction)
    replacements, scopes = resolve_correction_selection(
        test_db, [{"requirement_id": failed}]
    )
    result = materialize_deployment_qa_stage(
        test_db,
        **_subject(),
        agent_plan=str(correction),
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed}),
        commit=False,
    )
    corrected = result["created_requirement_ids"]
    assert corrected
    declare_replacements(test_db, replacements, materialized_requirement_ids=corrected)
    test_db.commit()
    execution = begin_plan_execution(
        test_db,
        **_subject(),
        plan=str(correction),
        actor_id="2",
        session_id="correction",
    )
    assert {row["requirement_id"] for row in execution["roster"]} == set(corrected)
    assert execution["deployment_member_item_id"] == MEMBERS[0]
    _complete_case(test_db, execution)
    assert current_item_qa(
        test_db, run_id=RUN, item_id=MEMBERS[0], current_stage=STAGE
    ).accepted
    assert _snapshot(test_db, RUN)["item_qa_plan_owners"][str(plan)] == MEMBERS[0]


def test_singleton_refresh_preserves_another_members_passed_contract(test_db):
    plan, failed = _single(test_db)
    _attach(test_db, MEMBERS[1], plan)
    materialize_deployment_qa_stage(test_db, **_subject(MEMBERS[1]))
    execution = begin_plan_execution(
        test_db, **_subject(MEMBERS[1]), actor_id="2", session_id="late-owner"
    )
    _complete_case(test_db, execution)
    _fail(test_db, failed)
    before = _snapshot(test_db, RUN)
    _correct(test_db, plan)
    with pytest.raises(QaPlanError, match="case already has passed acceptance"):
        rematerialize_for_deployment_stage(test_db, **_subject())
    assert _snapshot(test_db, RUN) == before


def test_missing_singleton_contract_still_refuses_historical_reconstruction(test_db):
    plan, _ = _single(test_db)
    payload = _snapshot(test_db, RUN)
    payload["plan_groups"].pop(str(plan))
    test_db.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(payload), RUN),
    )
    test_db.commit()
    with pytest.raises(
        QaPlanError, match="selected plan owner is missing or ambiguous"
    ):
        rematerialize_for_deployment_stage(test_db, **_subject())

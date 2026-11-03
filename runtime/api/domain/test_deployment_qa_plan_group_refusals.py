"""Closed group refusals retain their identity across registered dispatch."""

from uuid import uuid4

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import RUN, SLUG, _seed, _pass_group
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.yoke_function_dispatch import dispatch


@pytest.mark.parametrize("takeover", [False, True])
def test_closed_group_refusal_survives_permissions(test_db, takeover):
    from runtime.api.fixtures.dispatch_actor import register_session_actor

    actor_id = register_session_actor(test_db, "plan-group-qa")
    plan = _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    run_id = RUN
    if takeover:
        from runtime.api.domain.test_deployment_qa_plan_group_takeover import _take_over, NEW
        _take_over(test_db, plan)
        run_id = NEW
    response = dispatch({
        "function": "qa.plan.materialize", "request_id": str(uuid4()),
        "actor": {"actor_id": str(actor_id), "session_id": "plan-group-qa"},
        "target": {"kind": "deployment_run", "deployment_run_id": run_id},
        "payload": {"deployment_stage": "item-qa", "plan": SLUG},
    })
    assert not response.success
    assert response.error.code == "plan_group_not_open"
    assert "closed groups" in response.error.message
    assert "permission_denied" not in response.error.message


@pytest.mark.parametrize("function", ["qa.plan.materialize", "qa.plan_execution.begin"])
@pytest.mark.parametrize("selector", ["id", "slug"])
def test_member_owned_plan_refusal_names_holder_command(test_db, function, selector):
    from runtime.api.fixtures.dispatch_actor import register_session_actor
    from runtime.api.domain.test_deployment_qa_plan_groups import MEMBERS
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.deployment_qa_stage_materialization import stage_subject

    actor_id = register_session_actor(test_db, "plan-group-qa")
    plan = _seed(test_db, attached=MEMBERS[:1])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    response = dispatch({
        "function": function, "request_id": str(uuid4()),
        "actor": {"actor_id": str(actor_id), "session_id": "plan-group-qa"},
        "target": {"kind": "deployment_run", "deployment_run_id": RUN},
        "payload": {"deployment_stage": "item-qa", "plan": str(plan) if selector == "id" else SLUG},
    })
    ref = render_item_ref(test_db, MEMBERS[0])
    assert not response.success
    assert response.error.code == "plan_member_owned"
    assert f"plan {plan} ({SLUG})" in response.error.message
    assert f"belongs to {ref}; its claim holder runs it" in response.error.message
    assert f"yoke qa plan run --item {ref} --stage item-qa --project yoke" in response.error.message
    subject = stage_subject(
        test_db, run_id=RUN, stage_name="item-qa", member=MEMBERS[0],
        plan=str(plan), require_active=False,
    )
    assert subject["member_item_id"] == MEMBERS[0]


def test_plan_run_help_teaches_member_and_shared_ownership(capsys):
    from yoke_cli.commands.qa_case import qa_plan_run

    assert qa_plan_run(["--help"]) == 0
    help_text = capsys.readouterr().out
    assert "two or more attachers at item QA entry" in help_text
    assert "--deployment-run-id RUN --plan P" in help_text
    assert "its claim holder runs it with --item PREFIX-N --stage STAGE" in help_text
    assert "plan_member_owned" in help_text

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

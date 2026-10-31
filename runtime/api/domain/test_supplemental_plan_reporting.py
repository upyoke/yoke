"""All acceptance reports expose plan debt and its target-qualified recovery."""

import json

from runtime.api.domain.test_run_settles_plan_on_other_target import ITEM
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _bodies,
    _claim,
    seed_session,
)
from runtime.api.fixtures.supplemental_credit import plan_pair, close_group
from yoke_core.domain.actor_permissions import (
    seed_roles_and_permissions,
    grant_actor_project_role,
)
from yoke_core.domain.deployment_run_other_target_members import (
    OwedRequirement,
    owed_on_other_targets,
    member_completion_blocker,
    notify_set_aside_members,
)
from yoke_core.domain.qa_gate_summary import render_gate_summary
from yoke_core.domain.qa_gate_summary_text import _format_text
from yoke_core.domain.qa_gates import GateTarget


def test_plan_debt_appears_in_notice_blocker_and_gate_summary(
    test_db, tmp_path, monkeypatch
):
    plan, _ = plan_pair(test_db, tmp_path, monkeypatch, proof=False)
    (owed,) = owed_on_other_targets(test_db, ITEM, "prod")
    assert owed == OwedRequirement(
        None, "post_deploy", "stage", "other-target-plan", owed.recovery
    )
    assert (
        "post-deploy plan other-target-plan phase post_deploy target stage"
        in member_completion_blocker(
            test_db,
            run_id="run-prod",
            item_id=ITEM,
        )
    )
    seed_roles_and_permissions(test_db)
    grant_actor_project_role(test_db, actor_id=1, project_id=1, role_name="owner")
    seed_session(test_db, "plan-holder", project_id=1)
    _claim(
        test_db,
        session_id="plan-holder",
        target_kind="item",
        scope_json=json.dumps({"item_id": ITEM}),
    )
    notify_set_aside_members(
        test_db,
        "run-prod",
        [{"item_id": ITEM, "project_id": 1, "public_ref": f"YOK-{ITEM}"}],
    )
    bodies = _bodies(test_db, f"other-target-set-aside:{ITEM}:run-prod")
    assert len(bodies) == 1
    assert "post-deploy plan other-target-plan on stage:" in bodies[0]
    summary = render_gate_summary(
        GateTarget(item_id=ITEM), str(test_db.info.dsn), transition_name="implemented"
    )
    assert summary["satisfied"] is False
    assert summary["plan_group_misses"] == [
        {
            "plan_id": plan,
            "plan_slug": "other-target-plan",
            "target_env": "stage",
            "recovery": owed.recovery,
        }
    ]
    assert "Post-deploy plans not credited: 1" in _format_text(summary)
    close_group(test_db, "run-stage")
    summary = render_gate_summary(
        GateTarget(item_id=ITEM), str(test_db.info.dsn), transition_name="implemented"
    )
    assert summary["satisfied"] is True
    assert summary["plan_group_misses"] == []

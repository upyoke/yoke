"""A release owes a plan by its post-deploy attachment, never its other phases."""

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_member_plans import members_plan_ids
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups

RUN = "run-attachment-phase"
DOUBLE, VERIFICATION_ONLY = 9971, 9972


def _attach(conn, member, plan_id, transition, phase):
    conn.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,%s,%s,'2026-10-01T00:00:00Z')",
        (member, plan_id, transition, phase),
    )


def test_only_the_post_deploy_attachment_owes_the_plan_once(test_db):
    plan = _plan(test_db)
    stages = _stages(plan)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=(DOUBLE, VERIFICATION_ONLY))
    test_db.execute(
        "UPDATE items SET status='release' WHERE id=ANY(%s)",
        ([DOUBLE, VERIFICATION_ONLY],),
    )
    _attach(test_db, DOUBLE, plan, "reviewing-implementation", "verification")
    _attach(test_db, DOUBLE, plan, "release", "post_deploy")
    _attach(test_db, VERIFICATION_ONLY, plan, "reviewing-implementation", "verification")
    test_db.commit()

    assert members_plan_ids(test_db, [DOUBLE, VERIFICATION_ONLY], RUN) == {
        DOUBLE: {plan},
        VERIFICATION_ONLY: set(),
    }
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, RUN, "item-qa")
    assert group.plan_id == plan and group.open

"""A later group answers only members missing from prior closed coverage."""

from runtime.api.domain.test_deployment_qa_plan_groups import (
    RUN, SLUG, MEMBERS, _seed, _attach, _pass_group,
)
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups, member_group_blockers
from yoke_core.domain.deployment_qa_plan_groups import run_groups, owing_members
from yoke_core.domain.deployment_qa_plan_group_dispatch import _group_lines


def test_late_attacher_waits_without_reopening_covered_members(test_db):
    plan = _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    _pass_group(test_db)
    _attach(test_db, MEMBERS[2], plan)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    first, second = run_groups(test_db, RUN, "item-qa")
    assert first.closed and second.open
    assert owing_members(test_db, RUN, plan) == [MEMBERS[2]]
    assert member_group_blockers(test_db, RUN, "item-qa", MEMBERS[0]) == []
    assert member_group_blockers(test_db, RUN, "item-qa", MEMBERS[2])
    line = _group_lines(test_db, RUN, "item-qa", [second], str)[0]
    assert str(MEMBERS[2]) in line
    assert str(MEMBERS[0]) not in line
    _pass_group(test_db)
    first, second = run_groups(test_db, RUN, "item-qa")
    assert first.covered_item_ids == tuple(MEMBERS[:2])
    assert second.covered_item_ids == (MEMBERS[2],)


def test_item_selector_materializes_group_without_member_copy(test_db):
    from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage

    _seed(test_db)
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    materialize_deployment_qa_stage(
        test_db, deployment_run_id=RUN, deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0], agent_plan=SLUG,
    )
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE plan_id IS NOT NULL "
        "AND deployment_member_item_id IS NOT NULL"
    ).fetchone()[0] == 0

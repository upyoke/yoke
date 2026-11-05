"""Shared plan groups keep their human acceptance gate."""

from unittest import mock
from runtime.api.domain.deployment_qa_plan_group_scenarios_test_support import (
    _form,
)
from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    RUN,
    MEMBERS,
    _attach,
    _begin,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _stages,
    _seed_run,
    _complete_case,
)
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import group_subject
from yoke_core.domain.deployment_qa_plan_groups import run_groups


def test_a_group_needing_human_acceptance_stays_open_until_accepted(test_db):
    from yoke_core.domain.decision_request_resolution import resolve_decision_request

    reviewer = 9899
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (reviewer,),
    )
    plan_id = _plan(test_db)
    stages = _stages(
        plan_id,
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(test_db, member, plan_id)
    _form(test_db)

    def settle():
        (group,) = run_groups(test_db, [RUN], "item-qa")
        return settle_group(
            test_db, group_subject(test_db, RUN, "item-qa", group, require_active=False)
        )

    _complete_case(test_db, _begin(test_db))
    assert not settle()["accepted"]
    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.open and group.covered_item_ids is None
    (request_id,) = test_db.execute(
        "SELECT id FROM decision_requests WHERE kind='qa_needs_review' AND status='pending'"
    ).fetchone()

    with mock.patch(
        "yoke_core.domain.deployment_run_driver_notice.push_run_scoped_notice",
        return_value="delivered",
    ):
        resolve_decision_request(
            test_db,
            int(request_id),
            actor_id=reviewer,
            action="approve",
            note="Reviewed the plan group for the release.",
        )
        settle()

    (group,) = run_groups(test_db, [RUN], "item-qa")
    assert group.closed and group.covered_item_ids == tuple(sorted(MEMBERS))

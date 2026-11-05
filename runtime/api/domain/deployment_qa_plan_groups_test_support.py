# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group

from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)

from yoke_core.domain.deployment_qa_plan_groups import (
    retract_unattached_groups,
    run_groups,
)

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

RUN = "run-plan-groups"

MEMBERS = (9911, 9912, 9913)

SLUG = "release-smoke"


def _seed(conn, attached=MEMBERS):
    plan_id = _plan(conn)
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS)
    for member in attached:
        _attach(conn, member, plan_id)
    return plan_id


def _attach(conn, member, plan_id):
    conn.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy','2026-10-28T00:00:00Z')",
        (member, plan_id),
    )
    conn.commit()


def _begin(conn, member=None):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        plan=SLUG,
        actor_id="2",
        session_id="plan-group-qa",
    )


def _pass_group(conn):
    execution = _begin(conn)
    _complete_case(conn, execution)
    group = run_groups(conn, [RUN], "item-qa")[-1]
    if not group.closed:
        settle_group(
            conn, group_subject(conn, RUN, "item-qa", group, require_active=False)
        )
    return execution

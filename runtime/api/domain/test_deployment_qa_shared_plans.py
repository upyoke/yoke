"""Deployment item-qa fixtures: a run whose members attach one post-deploy plan.

Plan-group behavior is tested in ``test_deployment_qa_plan_groups`` and
``test_deployment_qa_plan_group_execution``; these helpers stay importable for
the tests that seed a member's own item-qa subject.
"""

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


RUN = "run-shared-plans"
MEMBERS = (9901, 9902)


def _seed(conn):
    plan_id = _plan(conn)
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(conn, member, plan_id)
    return plan_id


def _attach(conn, member, plan_id):
    conn.execute(
        "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy','2026-10-14T00:00:00Z')",
        (member, plan_id),
    )
    conn.commit()


def _materialize(conn, member):
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )


def _begin(conn, member):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id="shared-qa",
    )


def _fail(conn, requirement_id):
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,raw_result,started_at,completed_at,created_at) "
        "VALUES (%s,'worktree_run','plan_case','fail','shared probe failed',"
        "'2026-10-14T00:00:00Z','2026-10-14T00:00:01Z','2026-10-14T00:00:01Z')",
        (requirement_id,),
    )
    conn.commit()


__all__ = [
    "MEMBERS",
    "RUN",
    "_attach",
    "_begin",
    "_fail",
    "_materialize",
    "_plan",
    "_seed",
    "_seed_run",
    "_stages",
]

"""A member's own item cases progress while a plan group is still unfinished."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
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
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

OWN = "member-own-command"


def _seed(conn):
    """The stage names each member's own cases; every member attaches the group plan."""
    group_plan = _plan(conn)
    own_plan = _plan(conn, OWN)
    stages = _stages(own_plan)
    _seed_run(conn, run_id=RUN, stages=stages, members=MEMBERS)
    for member in MEMBERS:
        _attach(conn, member, group_plan)
    ensure_groups(conn, RUN, "item-qa")
    conn.commit()
    for member in MEMBERS:
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    return group_plan, own_plan


def _begin(conn, *, member=None, plan=None, session):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        plan=plan,
        actor_id="2",
        session_id=session,
    )


def _group_runs(conn, plan_id):
    return conn.execute(
        "SELECT COUNT(*) FROM qa_runs r JOIN qa_requirements q "
        "ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s AND q.plan_id=%s",
        (RUN, plan_id),
    ).fetchone()[0]


@pytest.mark.parametrize("group_live", [False, True])
def test_member_cases_progress_without_running_or_waiting_on_the_group(
    test_db, group_live
):
    group_plan, own_plan = _seed(test_db)
    member = MEMBERS[1]
    group = _begin(test_db, plan=SLUG, session="group-qa") if group_live else None

    execution = _begin(test_db, member=member, session="member-owner")

    assert execution["state"] == "active"
    assert execution["deployment_member_item_id"] == member
    assert execution["execution_target"]["deployment"]["member_item_id"] == member
    assert {row["plan_id"] for row in execution["roster"]} == {own_plan}
    _complete_case(test_db, execution)
    assert _group_runs(test_db, group_plan) == 0
    (open_group,) = run_groups(test_db, [RUN], "item-qa")
    assert open_group.open

    if group is None:
        group = _begin(test_db, plan=SLUG, session="group-qa")
    assert group["deployment_member_item_id"] is None
    _complete_case(test_db, group)
    settle_group(
        test_db, group_subject(test_db, RUN, "item-qa", open_group, require_active=False)
    )
    (closed,) = run_groups(test_db, [RUN], "item-qa")
    assert sorted(closed.covered_item_ids) == sorted(MEMBERS)


def test_private_member_probe_reads_member_cases_finished_before_the_group(
    test_db, monkeypatch
):
    from runtime.api.tools import private_member_qa_probe

    def read_proof(argv, **kwargs):
        rows = test_db.execute(argv[3]).fetchall()
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {"success": True, "result": {"rows": [list(row) for row in rows]}}
            ),
        )

    monkeypatch.setenv("DEPLOYMENT_RUN_ID", RUN)
    monkeypatch.setattr(private_member_qa_probe.subprocess, "run", read_proof)
    _seed(test_db)
    execution = _begin(test_db, member=MEMBERS[1], session="member-owner")
    assert private_member_qa_probe.main() == 1
    _complete_case(test_db, execution)
    assert private_member_qa_probe.main() == 0

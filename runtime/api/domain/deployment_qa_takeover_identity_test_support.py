# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from copy import deepcopy

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution

from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def _execution(conn, monkeypatch, *, apply=True, plan=None):
    plan = plan or create_smoke_plan(conn, project="yoke", slug="run-takeover-identity")
    stages = item_qa_stage_definitions(plan)
    stages[1].update(name=takeover.RUN_QA_STAGE, scope="run")
    seed_run_standing_on_qa_stage(
        conn,
        run_id=takeover.OLD,
        project="yoke",
        stages=stages,
        members=(takeover.WAITING,),
        lineage=takeover.OLD_LINEAGE,
    )
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=%s",
        (f"flow-{takeover.OLD}", takeover.WAITING),
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=takeover.RUN_QA_STAGE,
    )
    result = begin_plan_execution(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=takeover.RUN_QA_STAGE,
        actor_id="1",
        session_id=takeover.DRIVER_SESSION,
    )
    takeover._seed_new(conn)
    takeover._contains(monkeypatch)
    takeover.take_over_waiting_run(
        conn,
        takeover.NEW,
        session_id=takeover.DRIVER_SESSION,
        apply=apply,
    )
    return select_plan_execution(conn, result["id"], lock=False)


def _group_execution(test_db, monkeypatch):
    """A plan group's walk in flight when a successor run takes the release over."""
    from runtime.api.domain import (
        deployment_qa_plan_groups_test_support as shared,
    )
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

    shared._seed(test_db)
    ensure_groups(test_db, shared.RUN, "item-qa")
    test_db.commit()
    execution = shared._begin(test_db, shared.MEMBERS[0])
    assert execution["deployment_member_item_id"] is None
    test_db.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{shared.RUN}", list(shared.MEMBERS)),
    )
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at) SELECT %s,project_id,flow,target_tier,"
        "target_environment_id,%s,'created',created_at FROM deployment_runs WHERE id=%s",
        (takeover.NEW, takeover.NEW_LINEAGE, shared.RUN),
    )
    takeover._contains(monkeypatch)
    assert (
        takeover.take_over_waiting_run(
            test_db,
            takeover.NEW,
            session_id=takeover.DRIVER_SESSION,
        )
        == shared.RUN
    )
    execution = select_plan_execution(test_db, execution["id"], lock=False)
    assert execution["deployment_run_id"] == takeover.NEW
    validate_deployment_execution_target(test_db, execution)
    return execution

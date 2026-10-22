"""A transferred execution keeps its admitted target under its current owner."""

from copy import deepcopy

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
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


def _execution(conn, monkeypatch, *, apply=True):
    plan = create_smoke_plan(conn, project="yoke", slug="run-takeover-identity")
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


@pytest.mark.parametrize("apply", [False, True])
def test_real_run_execution_continues_before_successor_deploys(
    test_db, monkeypatch, apply
):
    execution = _execution(test_db, monkeypatch, apply=apply)
    assert execution["deployment_run_id"] == takeover.NEW
    assert execution["execution_target"]["deployment"]["run_id"] == takeover.OLD
    assert execution["execution_target"]["deployment"]["member_item_id"] is None
    validate_deployment_execution_target(test_db, execution)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("tenant", "id", -1),
        ("project", "id", -1),
        ("deployment", "member_item_id", takeover.WAITING),
        ("deployment", "stage", "another-stage"),
        ("endpoints", "app_url", "https://wrong.example.test"),
    ],
)
def test_takeover_rejects_another_subject_or_origin(
    test_db, monkeypatch, section, key, value
):
    execution = deepcopy(_execution(test_db, monkeypatch))
    execution["execution_target"][section][key] = value
    with pytest.raises(ValueError):
        validate_deployment_execution_target(test_db, execution)


def _shared_execution(test_db, monkeypatch):
    from runtime.api.domain import test_deployment_qa_shared_plans as shared

    shared._seed(test_db)
    for member in shared.MEMBERS:
        shared._materialize(test_db, member)
    execution = shared._begin(test_db, shared.MEMBERS[0])
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


def test_shared_execution_keeps_its_exact_group_after_takeover(test_db, monkeypatch):
    execution = _shared_execution(test_db, monkeypatch)
    from yoke_core.domain.deployment_run_terminalization import terminalize_run_on

    terminalize_run_on(
        test_db,
        takeover.NEW,
        disposition="failed",
        reason="deployment failed",
        actor_id=1,
        session_id=takeover.DRIVER_SESSION,
    )
    from yoke_core.domain.agent_mission_cleanup import cleanup_execution

    # Deployment failure does not turn an inherited walk into terminal cleanup.
    assert not cleanup_execution(test_db, execution)
    validate_deployment_execution_target(test_db, execution)
    third = "shared-qa-recovery"
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at) SELECT %s,project_id,flow,target_tier,"
        "target_environment_id,%s,'created',created_at FROM deployment_runs WHERE id=%s",
        (third, "d" * 40, takeover.NEW),
    )
    assert (
        takeover.take_over_waiting_run(
            test_db,
            third,
            session_id=takeover.DRIVER_SESSION,
        )
        == takeover.NEW
    )
    execution = select_plan_execution(test_db, execution["id"], lock=False)
    assert execution["deployment_run_id"] == third
    validate_deployment_execution_target(test_db, execution)
    execution["execution_target"]["deployment"]["shared_plan"]["source_revision"] = (
        "changed"
    )
    with pytest.raises(ValueError, match="qa_execution_target_unowned"):
        validate_deployment_execution_target(test_db, execution)


def test_completion_callback_resolves_owner_again_after_its_commit(
    test_db, monkeypatch
):
    from yoke_core.domain.deployment_qa_stage_settlement import settle_execution

    execution = _execution(test_db, monkeypatch)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='completed' WHERE id=%s",
        (execution["id"],),
    )
    test_db.commit()
    # The caller retained a pre-takeover copy across its result commit.
    stale = {**execution, "deployment_run_id": takeover.OLD, "state": "completed"}
    seen = []
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_settlement.settle_subject",
        lambda conn, **kwargs: seen.append(kwargs) or {"outcome": "passed"},
    )
    assert settle_execution(test_db, stale) is None
    assert seen == []  # The successor has not deployed or reached its QA gate.
    test_db.execute(
        "UPDATE deployment_runs SET status='executing',current_stage=%s WHERE id=%s",
        (takeover.RUN_QA_STAGE, takeover.NEW),
    )
    assert settle_execution(test_db, stale) == {"outcome": "passed"}
    assert seen == [
        {"run_id": takeover.NEW, "stage": takeover.RUN_QA_STAGE, "member": None}
    ]

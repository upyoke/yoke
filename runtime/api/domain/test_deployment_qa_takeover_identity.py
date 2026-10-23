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


@pytest.mark.parametrize("apply", [False, True])
def test_real_run_execution_continues_before_successor_deploys(
    test_db, monkeypatch, apply
):
    execution = _execution(test_db, monkeypatch, apply=apply)
    assert execution["deployment_run_id"] == takeover.NEW
    assert execution["execution_target"]["deployment"]["run_id"] == takeover.OLD
    assert execution["execution_target"]["deployment"]["member_item_id"] is None
    validate_deployment_execution_target(test_db, execution)
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context

    current_case = get_case_execution_context(
        test_db, requirement_id=execution["roster"][0]["requirement_id"]
    )
    from yoke_core.domain.deployment_run_project_sources import run_source_sha

    # Command checkouts follow the current owning run's source.
    assert current_case["deployment_source_revision"] == run_source_sha(
        test_db, takeover.NEW, int(current_case["project_id"])
    )
    assert (
        current_case["deployment_source_revision"]
        != execution["roster"][0]["deployment_source_revision"]
    )
    from yoke_core.domain.browser_qa_deployment_identity import (
        resolve_run_pinned_source,
    )
    from yoke_core.domain.browser_qa_freshness import _establish_deployment_freshness
    from yoke_core.domain.browser_qa_run_source import run_bound_identity
    from yoke_core.domain.deployment_qa_start_identity import start_identity_expectation
    from yoke_core.domain.served_revision_probe import ServedRevisionRead

    source = resolve_run_pinned_source(
        test_db, takeover.NEW, requirement_id=execution["roster"][0]["requirement_id"]
    )
    assert source["identity_scope"] == "environment"
    context = {
        "deployment_run_id": takeover.NEW,
        "run_source": source,
        "deployment_target": {
            "environment": "prod",
            "origin": "https://app.example.test",
            "identity_path": "/served-build",
        },
    }
    assert (
        run_bound_identity(
            takeover.NEW, context, expected_branch=None, expected_sha=None
        )[0]
        is None
    )
    assert start_identity_expectation(test_db, execution) is None
    for observed in (takeover.OLD_LINEAGE, "f" * 40):
        failure, origin, sha = _establish_deployment_freshness(
            "yoke",
            "main",
            source["sha"],
            context=context,
            fetch_identity=lambda _: ServedRevisionRead(status=200, body=observed),
        )
        assert failure is None
        assert (origin, sha) == ("https://app.example.test", observed)


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


@pytest.mark.parametrize("admission_changed", [False, True])
def test_stale_inherited_mission_continues_by_execution_before_deployment(
    test_db, monkeypatch, tmp_path, admission_changed
):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.domain.qa_plan_execution_lifecycle import (
        finish_plan_execution,
        STALE_PLAN_EXECUTION_REASON,
    )
    from yoke_core.domain.handlers.qa_plan_execution_reentry import (
        handle_execution_reentry,
    )
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )

    configure_test_machine(test_db, tmp_path, monkeypatch)
    sync_machine_qa_pack_methods(test_db)
    plan = create_smoke_plan(test_db, project="yoke", slug="inherited-mission")
    replace_plan_cases(
        test_db,
        plan_id=plan,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": "Continue the recorded exploration",
                "expected_outcome": "Return findings",
                "method_config": {"executor": "informed_subagent"},
                "host_baselines": ["fresh-host"],
            }
        ],
    )
    execution = _execution(test_db, monkeypatch, plan=plan)
    finish_plan_execution(
        test_db, execution, state="aborted", reason=STALE_PLAN_EXECUTION_REASON
    )
    if admission_changed:
        from yoke_core.domain import qa_plan_execution_begin
        from yoke_core.domain.qa_plan_execution_begin_admission import (
            BeginInputsChanged,
        )

        def changed(*args, **kwargs):
            raise BeginInputsChanged(takeover.NEW)

        monkeypatch.setattr(qa_plan_execution_begin, "begin_plan_execution", changed)
    outcome = handle_execution_reentry(
        FunctionCallRequest(
            function="qa.plan_execution.resume",
            target=TargetRef(kind="global"),
            actor=ActorContext(actor_id="1", session_id=takeover.DRIVER_SESSION),
            payload={"execution_id": execution["id"], "continue_mission": True},
        )
    )
    if admission_changed:
        assert not outcome.primary_success
        assert "qa_continuation_source_changed" in str(outcome.error)
        assert (
            select_plan_execution(test_db, execution["id"], lock=False)["state"]
            == "aborted"
        )
        return
    assert outcome.primary_success, outcome.error
    continued = select_plan_execution(
        test_db, outcome.result_payload["execution_id"], lock=False
    )
    assert continued["continues_execution_id"] == execution["id"]
    assert continued["deployment_run_id"] == takeover.NEW
    assert continued["execution_target_digest"] == execution["execution_target_digest"]
    assert continued["roster"][0]["host_baseline"] == "fresh-host"
    from yoke_core.domain.qa_plan_execution_continuation import contract_baselines

    assert contract_baselines(continued, continued["roster"][0]) == ()

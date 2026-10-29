"""Release plan-group contracts at authoring, routing, enrollment and cutover."""

import importlib
import shlex

from runtime.api.domain.test_deployment_run_carried_membership_enrollment import (
    _flows,
    RELEASE_FLOW,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_recovery_command import deploy_command


def test_merged_dash_is_enrolled_before_closeout_finishes(
    test_db, tmp_path, monkeypatch
):
    _flows(test_db)
    item_id = 9541
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="reviewing-implementation",
        deployment_flow=RELEASE_FLOW,
    )
    repo, baseline, tip = release_repository(tmp_path, "closeout")
    record_landing_receipt(test_db, item_id, branch="closeout", tip=tip)
    # Task review after the landing must not look like an item reopening.
    test_db.execute(
        "INSERT INTO item_status_transitions "
        "(item_id,task_num,from_status,to_status,created_at) "
        "VALUES(%s,1,'implementing','reviewing-implementation',clock_timestamp())",
        (item_id,),
    )
    serve_repository(monkeypatch, repo)
    insert_run(
        test_db,
        "run-before-closeout",
        lineage=baseline,
        status="succeeded",
        flow=RELEASE_FLOW,
    )
    insert_run(
        test_db, "run-during-closeout", lineage=tip, status="created", flow=RELEASE_FLOW
    )
    enrolled = enroll_carried_members(test_db, "run-during-closeout")
    assert len(enrolled) == 1
    assert (
        test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s",
            ("run-during-closeout",),
        ).fetchone()[0]
        == item_id
    )
    assert carried_membership_refusal(test_db, "run-during-closeout") is None
    test_db.execute("UPDATE items SET status='implementing' WHERE id=%s", (item_id,))
    from yoke_core.domain.deployment_run_landed_closeout import carried_release_members

    assert item_id not in carried_release_members(test_db, [item_id])


def test_cutover_drops_old_index_and_boot_does_not_recreate_it(test_db):
    from yoke_core.domain.qa_deployment_scope_schema import EXECUTION_SCOPE_INDEX_SQL

    migration = importlib.import_module(
        "yoke_core.domain.migrations.0096_qa_execution_target_scope"
    )
    test_db.execute(
        "CREATE UNIQUE INDEX idx_qa_plan_executions_deployment_stage_active "
        "ON qa_plan_executions(deployment_run_id,deployment_stage,session_id) "
        "WHERE deployment_run_id IS NOT NULL AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NULL AND state IN "
        "('active','waiting','walking','awaiting_walk_review')"
    )
    migration.apply(test_db)
    migration.invariants(test_db)
    for statement in EXECUTION_SCOPE_INDEX_SQL.split(";"):
        if statement.strip():
            test_db.execute(statement)
    migration.invariants(test_db)
    assert migration.MINIMUM_SERVING_VERSION == "next-release"


def test_candidate_route_precedes_full_scope_and_detached_branch_checks(
    tmp_path, monkeypatch
):
    from yoke_core.tools import pytest_remote_selection as selection

    monkeypatch.setattr(
        selection,
        "required_local_project",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("remote route consulted")),
    )
    route = selection.resolve_route(
        tmp_path,
        pytest_args=[],
        impacted_base=None,
        env={"YOKE_QA_CANDIDATE_TREE": "bound"},
    )
    assert isinstance(route, selection.LocalRoute)


def test_recovery_command_names_connection_and_run(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "test-control-plane")
    assert shlex.split(deploy_command("run-release-groups")) == [
        "yoke",
        "--env",
        "test-control-plane",
        "watch",
        "deploy",
        "--",
        "run-release-groups",
    ]


def test_string_target_does_not_crash_release_closeout():
    from yoke_core.domain.release_wait_facts import _attached_plan_ids

    assert (
        _attached_plan_ids(
            {"qa_plan_attachments": []}, [{"scope": "item", "target": "prod"}]
        )
        == []
    )


def test_materialize_infers_project_from_deployment_run(monkeypatch):
    from yoke_cli.commands.adapters import qa_execution_subjects as cli

    calls = []
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        cli, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    assert (
        cli.qa_plan_materialize_for_item(
            [
                "--deployment-run-id",
                "run-project-inference",
                "--stage",
                "run-qa",
                "--plan",
                "smoke",
            ]
        )
        == 0
    )
    assert calls[0]["target"].project_id is None
    assert calls[0]["target"].deployment_run_id == "run-project-inference"


def test_run_scoped_stage_returns_its_plan_to_the_driver(test_db):
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _plan,
        _seed_run,
        _stages,
    )
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )
    from yoke_core.domain.deployment_qa_pending_plans import pending_stage_plans

    plan_id = _plan(test_db, "run-scoped-automatic")
    stages = _stages(plan_id)
    stages[1]["scope"] = "run"
    run_id = "run-scoped-automatic-plans"
    _seed_run(test_db, run_id=run_id, stages=stages, members=())
    assert (
        materialize_and_gate_deployment_qa_stage(test_db, stages[1], run_id=run_id)[0]
        == -4
    )
    assert pending_stage_plans(test_db, stages[1], run_id) == [
        {"plan": "run-scoped-automatic", "project": "yoke", "target_digest": ""},
    ]

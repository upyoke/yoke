"""Migration 0094 deletes only unused post-deploy plan copies, and refuses old runs."""

import importlib
import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_expected_catalog import parse_expected_schema

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0094_delete_post_deploy_item_qa_copies"
)


def _plan(conn, slug="smoke") -> int:
    return int(
        conn.execute(
            "INSERT INTO qa_plans (project_id, slug, name, created_at, updated_at) "
            "VALUES (1, %s, 'Smoke', '2026-10-28T00:00:00Z', '2026-10-28T00:00:00Z') "
            "RETURNING id",
            (slug,),
        ).fetchone()[0]
    )


def _copy(conn, item_id, plan_id, **extra) -> int:
    return int(
        insert_qa_requirement(
            conn,
            item_id=item_id,
            qa_kind="plan_case",
            qa_phase="post_deploy",
            plan_id=plan_id,
            **{"plan_case_key": "home", **extra},
        )["id"]
    )


def _member(conn, run_id, item_id, snapshot=None) -> None:
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at, requirement_snapshot) "
        "VALUES (%s, %s, '2026-10-28T00:00:00Z', %s)",
        (run_id, item_id, json.dumps(snapshot or {"schema": 1, "requirements": []})),
    )


def _ids(conn) -> set[int]:
    return {int(row[0]) for row in conn.execute("SELECT id FROM qa_requirements")}


def test_deletes_only_unreferenced_copies_outside_unfinished_runs(test_db) -> None:
    for item_id in (1, 2, 3):
        insert_item(test_db, id=item_id, status="implemented")
    plan_id = _plan(test_db)
    unused = _copy(test_db, 1, plan_id)
    with_run = _copy(test_db, 1, plan_id, plan_case_key="login")
    insert_qa_run(test_db, qa_requirement_id=with_run, qa_kind="plan_case")
    successor = _copy(test_db, 1, plan_id, plan_case_key="cart")
    superseded = _copy(
        test_db, 1, plan_id, plan_case_key="cart-old", superseded_by_requirement_id=successor
    )
    insert_deployment_run(test_db, id="run-live", status="executing")
    _member(test_db, "run-live", 2)
    in_live_run = _copy(test_db, 2, plan_id)
    item_case = int(insert_qa_requirement(test_db, item_id=3, qa_phase="post_deploy")["id"])
    run_row = int(
        insert_qa_requirement(
            test_db, item_id=None, deployment_run_id="run-live", qa_phase="post_deploy",
            plan_id=plan_id, plan_case_key="home",
        )["id"]
    )
    test_db.commit()

    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)

    remaining = _ids(test_db)
    assert unused not in remaining
    assert {with_run, successor, superseded, in_live_run, item_case, run_row} <= remaining
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE


def test_refuses_while_an_unfinished_run_holds_old_model_plan_rows(test_db) -> None:
    insert_item(test_db, id=1, status="implemented")
    plan_id = _plan(test_db)
    insert_deployment_run(test_db, id="run-old", status="executing")
    _member(
        test_db, "run-old", 1, {"schema": 1, "requirements": [], "plans": [{"plan": {"id": plan_id}}]}
    )
    unused = _copy(test_db, 1, plan_id)
    test_db.commit()

    with pytest.raises(RuntimeError, match="old_model_plan_runs_unfinished: .*run-old"):
        MIGRATION.apply(test_db)
    test_db.rollback()
    assert unused in _ids(test_db)

    test_db.execute("UPDATE deployment_runs SET status='succeeded' WHERE id='run-old'")
    test_db.commit()
    MIGRATION.apply(test_db)
    assert unused not in _ids(test_db)


def test_refuses_on_a_shared_row_without_a_group_id(test_db) -> None:
    insert_item(test_db, id=1, status="implemented")
    plan_id = _plan(test_db)
    insert_deployment_run(test_db, id="run-shared", status="executing")
    _member(test_db, "run-shared", 1)
    target = {"deployment": {"run_id": "run-shared", "shared_plan": {"plan_id": plan_id}}}
    insert_qa_requirement(
        test_db, item_id=None, deployment_run_id="run-shared", qa_phase="post_deploy",
        plan_id=plan_id, plan_case_key="home", execution_target_json=json.dumps(target),
    )
    test_db.commit()
    with pytest.raises(RuntimeError, match="run-shared"):
        MIGRATION.apply(test_db)
    test_db.rollback()


def test_plan_group_rows_with_a_group_id_do_not_block(test_db) -> None:
    insert_item(test_db, id=1, status="implemented")
    plan_id = _plan(test_db)
    insert_deployment_run(test_db, id="run-new", status="executing")
    _member(test_db, "run-new", 1)
    marker = {"plan_id": plan_id, "group_id": "run-new:1"}
    target = {"deployment": {"run_id": "run-new", "shared_plan": marker}}
    insert_qa_requirement(
        test_db, item_id=None, deployment_run_id="run-new", qa_phase="post_deploy",
        plan_id=plan_id, plan_case_key="home", execution_target_json=json.dumps(target),
    )
    test_db.commit()
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)


def test_the_expected_schema_declares_covered_item_ids() -> None:
    assert "covered_item_ids" in parse_expected_schema()["qa_requirements"]

"""0120 against the real schema: old-model runs close and stages stop refusing.

A failed run composed from the obsolete member ``plans`` copy can no longer
be retried, so 0120 cancels it with an audit event; and a stage whose frozen
case named a Test Machine materializes again once 0120 converts the copy.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.migration_qa_hosts_by_os_test_support import migration
from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from yoke_core.domain.deployment_run_terminalization import TERMINALIZATION_EVENT

NAME = "0120_convert_snapshot_hosts_to_os"


def _old_model_run(conn, run_id, item, status="failed"):
    insert_item(conn, id=item, status="release")
    plan = int(conn.execute(
        "INSERT INTO qa_plans (project_id, slug, name, created_at, updated_at) "
        f"VALUES (1, 'smoke-{item}', 'Smoke', now(), now()) RETURNING id"
    ).fetchone()[0])
    insert_deployment_run(conn, id=run_id, status=status)
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES (%s,%s,now(),%s)",
        (run_id, item, json.dumps({"schema": 1, "requirements": [],
                                   "plans": [{"plan": {"id": plan}}]})),
    )
    insert_qa_requirement(
        conn, item_id=None, qa_kind="plan_case", qa_phase="post_deploy", plan_id=plan,
        plan_case_key="home", deployment_run_id=run_id, deployment_member_item_id=item,
        deployment_stage="item-qa",
    )


def test_old_model_failed_run_is_cancelled_and_cannot_be_retried(test_db):
    from yoke_core.domain.deployment_run_start import _prepare

    _old_model_run(test_db, "run-old-model", 9982)
    _old_model_run(test_db, "run-old-done", 9983, status="succeeded")
    migration(NAME).apply(test_db)
    statuses = dict(test_db.execute(
        "SELECT id,status FROM deployment_runs WHERE id IN ('run-old-model','run-old-done')"
    ).fetchall())
    assert statuses == {"run-old-model": "cancelled", "run-old-done": "succeeded"}
    event = test_db.execute(
        "SELECT envelope FROM events WHERE event_name=%s", (TERMINALIZATION_EVENT,)
    ).fetchall()
    assert len(event) == 1
    context = json.loads(event[0][0])["context"]
    assert context["run_id"] == "run-old-model"
    assert (context["prior_status"], context["final_status"]) == ("failed", "cancelled")
    assert context["reason"] == "old QA model; retry impossible after 0120"
    assert all(
        "plans" not in json.loads(raw)
        for (raw,) in test_db.execute(
            "SELECT requirement_snapshot FROM deployment_run_items"
        ).fetchall()
    )
    with pytest.raises(ValueError, match="cancelled"):
        _prepare(test_db, "run-old-model")
    migration(NAME).apply(test_db)
    migration(NAME).invariants(test_db)
    assert test_db.execute(
        "SELECT COUNT(*) FROM events WHERE event_name=%s", (TERMINALIZATION_EVENT,)
    ).fetchone()[0] == 1


def _pin_frozen_cases(conn, run_id):
    """Write a host name into every frozen copy of the run's smoke case."""
    raw = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    snapshot = json.loads(raw)
    copies = [
        *(c for s in snapshot.get("selections") or [] for c in s.get("cases") or []),
        *(c for g in (snapshot.get("plan_groups") or {}).values() for c in g["cases"]),
    ]
    assert copies, "the seeded run froze no plan case"
    for case in copies:
        case["method_config"] = {**case["method_config"], "test_machine_reason": "lab"}
    conn.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(snapshot), run_id),
    )


def test_stage_over_converted_snapshot_no_longer_refuses(test_db):
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    run_id, member = "run-frozen-pin", 9984
    requirement = seed_member_qa_case(test_db, run_id=run_id, member_item_id=member)
    record_case_verdict(test_db, requirement, "pass", evidence=True)
    _pin_frozen_cases(test_db, run_id)
    test_db.commit()
    stage = {"deployment_run_id": run_id, "deployment_stage": ITEM_QA_STAGE,
             "deployment_member_item_id": member}
    with pytest.raises(Exception, match="test_machine_name_forbidden"):
        materialize_deployment_qa_stage(test_db, **stage)
    test_db.rollback()
    migration(NAME).apply(test_db)
    materialize_deployment_qa_stage(test_db, **stage)
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s "
        "AND method_id IS NOT NULL AND retracted_at IS NULL",
        (run_id,),
    ).fetchone()[0] == 1

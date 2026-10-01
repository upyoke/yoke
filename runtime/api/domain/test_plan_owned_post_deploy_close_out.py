"""Plan snapshot and direct admission both satisfy their source at auto-close."""

from __future__ import annotations

import pytest

from runtime.api.domain import test_independent_member_delivery_close_out as delivery
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config


def _pass_case(conn, execution, ordinal):
    requirement_id = int(execution["roster"][ordinal]["requirement_id"])
    requirement = conn.execute(
        "SELECT method_config,execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    currency = stamp_executed_method_config(
        None,
        requirement["method_config"],
        execution_target_digest=requirement["execution_target_digest"],
    )
    now = "2026-09-14T00:02:00Z"
    qa_run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) "
        "VALUES (%s,'worktree_run','plan_case','pass',%s,%s,%s,%s) RETURNING id",
        (requirement_id, currency, now, now, now),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
        (qa_run_id, "evidence://admitted-copy", now),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": qa_run_id,
        },
    )


@pytest.mark.parametrize("admission", ["plan", "grouped-plan", "direct"])
def test_accepted_admitted_copies_auto_close_the_member(
    test_db, monkeypatch, admission
):
    _isolate_status_effects(monkeypatch)
    grouped = admission == "grouped-plan"
    plan_owned = admission != "direct"
    plan_id = _plan(test_db, f"source-{admission}")
    if grouped:
        replace_plan_cases(
            test_db,
            plan_id=plan_id,
            cases=[
                {
                    "case_key": "command-smoke",
                    "position": 1,
                    "method_id": "browser-inspection",
                    "instructions": "Inspect the deployed release on both hosts.",
                    "expected_outcome": "The deployed release is visible.",
                    "method_config": {
                        "steps": [
                            {"action": "navigate", "route": "/"},
                            {"action": "screenshot", "capture": True},
                        ]
                    },
                    "host_baselines": ["shell-preconfigured", "fresh-host"],
                }
            ],
        )
    monkeypatch.setattr(delivery, "_plan", lambda *_args: plan_id)
    run_id = f"run-source-{admission}"
    delivery._seed_final_run(test_db, run_id, shared_qa=False)
    member = delivery.MEMBER_A
    source_ids = []
    for baseline in ["shell-preconfigured", "fresh-host"] if grouped else [None]:
        source_id = _original_requirement(
            test_db, item_id=member, method_id="browser-inspection"
        )
        test_db.execute(
            "UPDATE qa_requirements SET target_env='prod',workflow_transition_id='release',"
            "plan_id=%s,plan_case_key=%s,host_baseline=%s WHERE id=%s",
            (
                plan_id if plan_owned else None,
                "command-smoke" if plan_owned else None,
                baseline,
                source_id,
            ),
        )
        source_ids.append(source_id)
    snapshot = snapshot_member_requirements(
        test_db,
        run_id=run_id,
        item_id=member,
        selection_json=requirement_selection(requirement_ids=tuple(source_ids)),
    )
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s "
        "WHERE run_id=%s AND item_id=%s",
        (snapshot, run_id, member),
    )
    test_db.commit()
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    copies = test_db.execute(
        "SELECT plan_id,plan_case_key,host_baseline FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_member_item_id=%s "
        "AND method_id IS NOT NULL ORDER BY id",
        (run_id, member),
    ).fetchall()
    if plan_owned:
        assert all(row["plan_id"] == plan_id for row in copies)
        assert all(row["plan_case_key"] == "command-smoke" for row in copies)
        assert len(copies) == (2 if grouped else 1)
        if grouped:
            assert {row["host_baseline"] for row in copies} == {
                "shell-preconfigured",
                "fresh-host",
            }
    else:
        assert any(row["plan_id"] is None for row in copies)
    assert delivery._status(test_db, member) == "release"
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id=f"qa-{admission}",
    )
    for ordinal in range(len(execution["roster"])):
        _pass_case(test_db, execution, ordinal)
        if grouped and ordinal == 0:
            assert not source_obligation_consumed(
                test_db, item_id=member, source_requirement_id=source_ids[0]
            )
            assert delivery._status(test_db, member) == "release"
    finish_plan_execution(test_db, execution, state="completed", reason="test-complete")
    assert delivery._status(test_db, member) == "done"
    assert delivery._status(test_db, delivery.MEMBER_B) == "release"
    for source_id in source_ids:
        assert source_obligation_consumed(
            test_db, item_id=member, source_requirement_id=source_id
        )
        assert (
            test_db.execute(
                "SELECT waived_at FROM qa_requirements WHERE id=%s", (source_id,)
            ).fetchone()["waived_at"]
            is None
        )
        assert (
            test_db.execute(
                "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s", (source_id,)
            ).fetchone()[0]
            == 0
        )

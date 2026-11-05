# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain import deployment_qa_shared_plans_test_support as shared

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover

from runtime.api.domain.deployment_qa_stage_execution_test_support import _stages

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _bodies,
    _claim,
    _project,
    seed_session,
)

from yoke_core.domain import delivery_evidence_ladder

from yoke_core.domain import deployment_qa_release_version as release_version

from yoke_core.domain import deployment_run_candidate_containment as containment

from yoke_core.domain.deployment_qa_failure_handoff import (
    failure_handoff_key,
    notify_member_qa_failure,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)

from yoke_core.domain.qa_plan_execution_store import (
    plan_execution_view,
    select_plan_execution,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.work_claim_targets import make_item_target

MEMBER = shared.MEMBERS[0]


@pytest.fixture(autouse=True)
def _pinned_release(monkeypatch):
    """Each delivered commit pins its own Yoke release."""
    monkeypatch.setattr(release_version, "_pin_file", lambda conn, pid: "pin.txt")
    monkeypatch.setattr(
        release_version, "_pinned_version", lambda conn, pid, sha, path: f"v-{sha[:6]}"
    )


def _plan(conn) -> int:
    plan_id = int(
        create_plan(
            conn,
            project="yoke",
            slug="successor-retry",
            name="Successor retry",
            infer_target_environment=False,
        )["id"]
    )
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": f"run {key}",
                "expected_outcome": "the command passes",
                "method_config": {"command": "true"},
            }
            for position, key in ((1, "carried-pass"), (2, "retried-fail"))
        ],
    )
    return plan_id


def _record(conn, execution, ordinal, verdict, *, created="2026-09-01T00:00:00Z"):
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    requirement_id = int(execution["roster"][ordinal]["requirement_id"])
    stamp = created
    config = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    raw = stamp_executed_method_config(
        f"{verdict} evidence",
        config,
        conn=conn,
        requirement_id=requirement_id,
        execution_target_digest=execution["execution_target_digest"],
    )
    run_id = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "raw_result,started_at,completed_at,created_at) VALUES "
            "(%s,'worktree_run','plan_case',%s,%s,%s,%s,%s) RETURNING id",
            (requirement_id, verdict, raw, stamp, stamp, stamp),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
        (run_id, f"evidence://{verdict}", stamp),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": verdict,
            "case_outcome": "passed" if verdict == "pass" else "failed",
            "run_id": run_id,
        },
    )
    return requirement_id, run_id


def _seed_member_execution(conn, monkeypatch, *, producer=HOLDER_A):
    """Each member walks the two cases its flow pins at the item stage."""
    plan_id = _plan(conn)
    stages = _stages(plan_id)
    stages[1]["cases"]["case_keys"] = ["carried-pass", "retried-fail"]
    shared._seed_run(conn, run_id=shared.RUN, stages=stages, members=shared.MEMBERS)
    for member in shared.MEMBERS:
        shared._materialize(conn, member)
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{shared.RUN}", list(shared.MEMBERS)),
    )
    _project(conn)
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=shared.RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="1",
        session_id=producer,
    )
    monkeypatch.setattr(
        delivery_evidence_ladder, "item_merge_identity", lambda conn, item: "e" * 40
    )
    takeover._contains(monkeypatch)
    return execution


def _take_over_and_deploy(
    conn,
    monkeypatch=None,
    state=containment.CONTAINED,
    *,
    observed_url="https://preview.example.test",
):
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at,composition_frozen_at,requirement_snapshot) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,'created',"
        "created_at,composition_frozen_at,requirement_snapshot FROM deployment_runs "
        "WHERE id=%s",
        (takeover.NEW, takeover.NEW_LINEAGE, shared.RUN),
    )
    assert (
        takeover.take_over_waiting_run(
            conn, takeover.NEW, session_id=takeover.DRIVER_SESSION
        )
        == shared.RUN
    )
    conn.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='deploy' WHERE id=%s",
        (takeover.NEW,),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=takeover.NEW,
        stage_name="deploy",
        correlation_id="successor-deploy-1",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=takeover.NEW,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url=observed_url,
        observed_release_lineage=takeover.NEW_LINEAGE,
        executor_receipt="test://successor-ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s",
        (takeover.NEW,),
    )
    conn.commit()
    if monkeypatch is not None:
        takeover._contains(monkeypatch, state)


def _release(view) -> str:
    return view["execution_target"]["endpoints"]["release_version"]

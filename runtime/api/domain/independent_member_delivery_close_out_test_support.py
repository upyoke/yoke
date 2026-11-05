# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _environment,
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _recipients,
)

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    _project,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import _ready_member

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from yoke_core.domain.deployment_delivery_close_out_notice import (
    notify_delivery_cleared,
)

from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
)

from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
    notify_item_qa_accepted,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_resume import (
    prior_deployment_qa_refusals,
)

from yoke_core.domain.deployment_run_completion_preconditions import refuse_succeeded

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)

from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config

MEMBER_A = 9931

MEMBER_B = 9932


def _status(conn: Any, item_id: int) -> str:
    return str(
        conn.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            "status"
        ]
    )


def _settle(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member: int | None,
    may_complete_run: bool = False,
) -> None:
    """Record a case pass with the target identity a real QA runner stamps."""
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=member,
        actor_id="2",
        session_id=f"{stage}-{member}",
    )
    requirement_id = int(execution["roster"][0]["requirement_id"])
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
        (qa_run_id, "evidence://scoped-case", now),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": qa_run_id,
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    if (
        may_complete_run
        and conn.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "succeeded"
    ):
        return
    assert deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=stage, member_item_id=member
    )["accepted"]


def _seed_final_run(
    conn: Any, run_id: str, *, shared_qa: bool, shared_approval: bool = False
) -> list[dict]:
    _project(conn)
    _environment(conn)
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT site,project_id,'prod',url,settings,created_at FROM environments "
        "WHERE name='stage' AND site IN (SELECT id FROM sites WHERE project_id=1)"
    )
    conn.commit()
    for item_id, holder in ((MEMBER_A, HOLDER_A), (MEMBER_B, HOLDER_B)):
        _ready_member(conn, item_id, holder)
    stages = _stages(_plan(conn, f"plan-{run_id}"))
    stages[1]["target"]["environment"] = "prod"
    if shared_approval:
        stages.insert(
            1,
            {
                "name": "approve-release",
                "step_runner": "human-approval",
                "stage_kind": "execution",
                "scope": "run",
                "approvals": {"roles": ["owner"], "actors": []},
            },
        )
    if shared_qa:
        run_qa = dict(stages[1])
        run_qa["name"] = "run-qa"
        run_qa["scope"] = "run"
        stages.append(run_qa)
    stages.append(
        {"name": "complete", "step_runner": "auto", "stage_kind": "execution"}
    )
    _seed_run(
        conn,
        run_id=run_id,
        stages=stages,
        members=(),
        existing_members=(MEMBER_A, MEMBER_B),
    )
    if shared_approval:
        conn.execute(
            "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s",
            (run_id,),
        )
    # The shared test seeder defaults to a stage target. Bind this test's
    # exact ready receipt and run target to the registered production target.
    prod_id = conn.execute(
        "SELECT id FROM environments WHERE name='prod' "
        "AND site IN (SELECT id FROM sites WHERE project_id=1)"
    ).fetchone()["id"]
    conn.execute(
        "UPDATE deployment_runs SET target_tier='persistent', "
        "target_environment_id=%s WHERE id=%s",
        (prod_id, run_id),
    )
    conn.execute(
        "UPDATE deployment_stage_receipts SET target_name='prod' WHERE run_id=%s",
        (run_id,),
    )
    conn.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE run_id=%s",
        (run_id,),
    )
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id IN (%s,%s)",
        (f"flow-{run_id}", MEMBER_A, MEMBER_B),
    )
    conn.commit()
    return stages

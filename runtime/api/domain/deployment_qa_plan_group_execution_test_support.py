# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _seed,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
)

from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group

from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

OTHER = "other-plan"


def _begin(conn, plan=SLUG, session="plan-group-qa", member=None):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        plan=plan,
        actor_id="2",
        session_id=session,
    )


def _fail_case(conn, execution):
    """Walk the group's first case to a failing verdict and finish the walk."""
    from yoke_core.domain.qa_plan_execution_state import (
        advance_plan_execution,
        finish_plan_execution,
    )

    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-10-28T00:00:01Z"
    run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,raw_result,"
        "started_at,completed_at,created_at) VALUES (%s,'worktree_run','plan_case',"
        "'fail','group probe failed',%s,%s,%s) RETURNING id",
        (requirement_id, now, now, now),
    ).fetchone()[0]
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "fail",
            "case_outcome": "failed",
            "run_id": int(run_id),
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-fail")
    return requirement_id


def _settle(conn, group):
    return settle_group(
        conn, group_subject(conn, RUN, "item-qa", group, require_active=False)
    )

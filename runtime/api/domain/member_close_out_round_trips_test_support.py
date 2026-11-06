# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    _project,
)

from runtime.api.domain.deployment_qa_plan_groups_test_support import _attach

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import HOLDER_A

from runtime.api.domain.no_obligation_member_close_out_test_support import _ready_member

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.statement_counter import CountingConnection

from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group

from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

RUNS = {
    "run-close-out-small": (1, (9911, 9912, 9913)),
    "run-close-out-large": (6, (9914, 9915, 9916, 9917, 9918)),
}


def _seed(conn, run_id: str) -> int:
    """A parked member attaching one plan; its siblings attach every plan.

    The release runs one plan group per attached plan and each group passes,
    so every member's plan obligation is credited.
    """
    count, (measured, *siblings) = RUNS[run_id]
    plans = [_plan(conn, f"{run_id}-{index}") for index in range(count)]
    stages = _stages(plans[0])
    stages[1].pop("cases")
    _ready_member(conn, measured, f"{HOLDER_A}-{run_id}")
    _seed_run(
        conn,
        run_id=run_id,
        stages=stages,
        members=tuple(siblings),
        existing_members=(measured,),
    )
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{run_id}", measured)
    )
    conn.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE run_id=%s",
        (run_id,),
    )
    _attach(conn, measured, plans[0])
    for sibling in siblings:
        for plan_id in plans:
            _attach(conn, sibling, plan_id)
    ensure_groups(conn, run_id, "item-qa")
    conn.commit()
    for index in range(count):
        _pass_group(conn, run_id, f"{run_id}-{index}")
    groups = run_groups(conn, [run_id], "item-qa")
    assert len(groups) == count and all(group.closed for group in groups)
    return measured


def _pass_group(conn, run_id: str, slug: str) -> None:
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=None,
        plan=slug,
        actor_id="2",
        session_id=f"group-qa-{slug}",
    )
    _complete_case(conn, execution)
    for group in run_groups(conn, [run_id], "item-qa"):
        if not group.closed:
            settle_group(
                conn,
                group_subject(conn, run_id, "item-qa", group, require_active=False),
            )
    conn.commit()

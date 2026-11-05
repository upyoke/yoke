# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain import deployment_qa_dispatch_preparation as preparation

from yoke_core.domain import deployment_qa_stage_gate as gate

from yoke_core.domain import deployment_qa_stage_materialization as materialization

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_run_member_removal import remove_member_on

from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removals,
)

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

RUN = "run-live-member-removal"

REMOVED = 9761

REMAINING = 9762


def _ready_run(conn):
    stages = _stages(_plan(conn))
    _seed_run(conn, run_id=RUN, stages=stages, members=(REMOVED, REMAINING))
    for member in (REMOVED, REMAINING):
        conn.execute("UPDATE items SET status='release' WHERE id=%s", (member,))
    materialization.materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=REMAINING,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=REMAINING,
        actor_id="2",
        session_id="remaining-member-qa",
    )
    _complete_case(conn, execution)
    conn.commit()
    return stages[-1]

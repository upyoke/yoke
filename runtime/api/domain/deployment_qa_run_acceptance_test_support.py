# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.domain.deployment_qa_stage_ordering_test_support import (
    _complete_failed,
    _stages as _ordered_stages,
)

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
    current_item_qa,
    member_qa_standings,
)

from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def _settle(conn: Any, *, run_id: str, stage: str, member: int | None) -> None:
    """Drive one stage subject all the way to a recorded acceptance."""
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
    _complete_case(conn, execution)
    assert deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=stage, member_item_id=member
    )["accepted"]


def _acceptance_requirement_id(conn: Any, run_id: str, stage: str) -> int:
    row = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND qa_kind=%s ORDER BY id DESC LIMIT 1",
        (run_id, stage, DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND),
    ).fetchone()
    assert row is not None
    return int(row["id"])

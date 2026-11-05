# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.qa_requirement_target_rebind import rebind_requirement


def _materialized_stage(conn: Any, run_id: str, member: int) -> None:
    plan_id = _plan(conn, f"{run_id}-smoke")
    _seed_run(conn, run_id=run_id, stages=_stages(plan_id), members=(member,))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )


def _edit_stage_settings(conn: Any, settings: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE environments SET settings=%s WHERE project_id=1 AND name='stage'",
        (json.dumps(settings),),
    )
    conn.commit()

# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from runtime.api.domain.agent_mission_qa_test_support import _materialize_mission

from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.agent_mission_recording import handle_agent_mission_access

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.qa_plan_execution_continuation import (
    CASE_EXECUTION_ERROR_REASON,
    PRE_HOST_ERROR_REASON,
    contract_baselines,
)

from yoke_core.domain.qa_plan_execution_lifecycle import (
    reap_stale_plan_executions,
)

from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
    finish_plan_execution,
    select_plan_execution,
)

MISSION_ACTOR = ActorContext(actor_id="1", session_id="session-agent-mission")

MISSION_TRANSITION = "reviewing-implementation"

LONG_AGO = "2026-01-01T00:00:00Z"


def _stop_reporting(conn: Any, execution_id: str) -> None:
    conn.execute(
        "UPDATE qa_plan_executions SET heartbeat_at=%s WHERE id=%s",
        (LONG_AGO, execution_id),
    )
    conn.commit()


def _swept_mission(
    conn: Any,
    tmp_path: Any,
    monkeypatch: Any,
    *,
    item_id: int,
) -> tuple[int, dict[str, Any]]:
    """Settle one mission execution exactly the way the stale sweep does."""
    configure_test_machine(conn, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(conn, item_id=item_id)
    execution = begin_plan_execution(
        conn,
        item_id=item_id,
        transition_id=MISSION_TRANSITION,
        actor_id=MISSION_ACTOR.actor_id,
        session_id=MISSION_ACTOR.session_id,
    )
    _stop_reporting(conn, str(execution["id"]))
    reaped = reap_stale_plan_executions(conn)
    assert [entry["reaped"] for entry in reaped] == [True]
    settled = select_plan_execution(conn, str(execution["id"]), lock=False)
    conn.rollback()
    return requirement_id, settled

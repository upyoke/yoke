# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from typing import Any

from unittest import mock

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers.machine_qa_plan_case import (
    handle_plan_case_begin,
    handle_plan_case_submit,
)

from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)

from yoke_core.domain.machine_qa_local_execution import (
    execute_machine_case_contract,
)

from yoke_core.domain import machine_qa_execution_protocol

from yoke_core.domain.coordination_claims import acquire, release

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from yoke_core.domain.work_claim_targets import make_qa_admission_target

ACTOR = ActorContext(actor_id="1", session_id="session-machine-plan")


def _request(
    function: str,
    *,
    item_id: int,
    execution_id: str,
    ordinal: int,
    requirement_id: int,
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ACTOR,
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "execution_id": execution_id,
            "ordinal": ordinal,
            "requirement_id": requirement_id,
            **(payload or {}),
        },
    )


def _active_lease_count(conn: Any) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind = 'qa_admission'"
        ).fetchone()[0]
    )


def _execute_begin_contract(response: Any) -> Any:
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready"
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        return execute_machine_case_contract(response.result_payload["execution"])
    finally:
        clear_host_control_factory()

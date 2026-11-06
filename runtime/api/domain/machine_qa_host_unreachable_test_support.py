# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from runtime.api.domain.qa_host_health_turns_test_support import (
    ACTOR,
    ITEM_ID,
    MACHINE,
    _begin,
    _notices,
    _record,
    _wait_state,
)

from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef

from yoke_contracts.machine_qa_execution import (
    HostControlExecutionContract,
    execution_contract_digest,
)

from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError

from yoke_core.domain import machine_qa_plan_case_execution

from yoke_core.domain.coordination_claims import acquire, active_claim, release

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_submit

from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)

from yoke_core.domain.machine_qa_local_execution import execute_machine_case_contract

from yoke_core.domain.qa_host_health import HOST_UNHEALTHY_REASON, host_unhealthy

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.work_claim_targets import make_qa_admission_target


def _plan(conn: Any, tmp_path: Path, monkeypatch: Any) -> tuple[dict, dict]:
    materialize_installer_campaign(conn, item_id=ITEM_ID)
    configure_test_machine(conn, tmp_path, monkeypatch)
    execution = begin_plan_execution(
        conn,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    return execution, execution["roster"][0]


def _submit(execution: dict, case: dict, payload: dict[str, Any]) -> Any:
    return handle_plan_case_submit(
        FunctionCallRequest(
            function="test_machine.plan_case.submit",
            actor=ACTOR,
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={
                "execution_id": str(execution["id"]),
                "ordinal": 0,
                "requirement_id": int(case["requirement_id"]),
                **payload,
            },
        )
    )
